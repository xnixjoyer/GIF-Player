#!/usr/bin/env python3
"""Pure player timing/motion helpers plus targeted GTK runtime patches.

The helpers in this module intentionally avoid importing GTK. This keeps the
geometry, frame pacing, GIF metadata normalization, and transition decisions
unit-testable without a Wayland compositor. ``install_runtime_patches`` is
called by the packaged bootstrap after the legacy GTK implementation has been
loaded; it changes only the narrow state transitions that need compositor-aware
coordination and leaves the public IPC/supervisor architecture intact.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
import time
from typing import Any, Iterator

DEFAULT_FRAME_DURATION_MS = 100
MIN_FRAME_DURATION_MS = 20
MAX_CATCHUP_FRAMES = 8
TRANSITION_FALLBACK_MS = 120


def normalize_frame_duration(value: Any) -> int:
    """Return a practical GIF frame duration while preserving fast animation."""

    try:
        duration = int(value)
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_FRAME_DURATION_MS
    if duration <= 0:
        return DEFAULT_FRAME_DURATION_MS
    return max(MIN_FRAME_DURATION_MS, duration)


def iter_composited_frames(image: Any) -> Iterator[tuple[Any, int]]:
    """Yield independent, fully composited RGBA frames and their durations.

    Pillow's GIF ``seek`` applies local palettes, transparency, delta-frame
    composition and disposal handling to the logical canvas. Copying the RGBA
    result prevents later seek operations from mutating an already stored frame.
    """

    total = max(1, int(getattr(image, "n_frames", 1)))
    for index in range(total):
        image.seek(index)
        rgba = image.convert("RGBA").copy()
        duration = normalize_frame_duration(image.info.get("duration"))
        yield rgba, duration


def premultiplied_bgra_bytes(rgba: Any) -> bytes:
    """Convert Pillow RGBA to Cairo ARGB32 bytes on little-endian Linux."""

    premultiplied = rgba.convert("RGBa")
    return premultiplied.tobytes("raw", "BGRa")


def cairo_surface_from_rgba(rgba: Any, cairo_module: Any) -> tuple[Any, bytearray]:
    """Create a Cairo surface and return its explicitly retained buffer."""

    buffer = bytearray(premultiplied_bgra_bytes(rgba))
    surface = cairo_module.ImageSurface.create_for_data(
        buffer,
        cairo_module.FORMAT_ARGB32,
        rgba.width,
        rgba.height,
        rgba.width * 4,
    )
    return surface, buffer


def jump_offset(progress: float, height: float) -> float:
    """Continuous half-sine hop with exact zero at both endpoints."""

    if not math.isfinite(progress) or not math.isfinite(height):
        return 0.0
    progress = min(1.0, max(0.0, float(progress)))
    if progress <= 0.0 or progress >= 1.0:
        return 0.0
    return math.sin(math.pi * progress) * float(height)


def is_fully_inside(
    x: float,
    y: float,
    width: float,
    height: float,
    bounds_width: float,
    bounds_height: float,
) -> bool:
    """Return whether a rectangle is completely inside monitor-local bounds."""

    values = (x, y, width, height, bounds_width, bounds_height)
    if not all(math.isfinite(float(value)) for value in values):
        return False
    return (
        x >= 0.0
        and y >= 0.0
        and width <= bounds_width
        and height <= bounds_height
        and x + width <= bounds_width
        and y + height <= bounds_height
    )


def manual_position(x: float, y: float) -> tuple[float, float]:
    """Normalize a manual position without applying monitor clamps."""

    x = float(x)
    y = float(y)
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError("position must be finite")
    return x, y


@dataclass(frozen=True)
class BounceAxis:
    position: float
    velocity: float
    oversized: bool = False


def bounce_axis(
    position: float,
    velocity: float,
    dt: float,
    bound: float,
    item_size: float,
) -> BounceAxis:
    """Advance one bounce axis with reflection and an oversized fallback.

    If the item cannot fit on an axis, there is no valid reflection interval.
    The stable fallback centers the oversized item on that axis and freezes that
    velocity component. The other axis can continue bouncing normally.
    """

    position = float(position)
    velocity = float(velocity)
    dt = max(0.0, float(dt))
    bound = max(0.0, float(bound))
    item_size = max(0.0, float(item_size))
    if not all(math.isfinite(value) for value in (position, velocity, dt, bound, item_size)):
        return BounceAxis(0.0, 0.0, True)

    extent = bound - item_size
    if extent <= 0.0:
        return BounceAxis(extent / 2.0, 0.0, True)
    if velocity == 0.0 or dt == 0.0:
        return BounceAxis(min(extent, max(0.0, position)), velocity, False)

    raw = position + velocity * dt
    period = 2.0 * extent
    phase = raw % period
    if phase <= extent:
        reflected = phase
        slope = 1.0
    else:
        reflected = period - phase
        slope = -1.0
    return BounceAxis(reflected, velocity * slope, False)


@dataclass(frozen=True)
class BounceStep:
    x: float
    y: float
    vx: float
    vy: float
    oversized_x: bool
    oversized_y: bool


def bounce_step(
    x: float,
    y: float,
    vx: float,
    vy: float,
    dt: float,
    bounds_width: float,
    bounds_height: float,
    item_width: float,
    item_height: float,
) -> BounceStep:
    horizontal = bounce_axis(x, vx, dt, bounds_width, item_width)
    vertical = bounce_axis(y, vy, dt, bounds_height, item_height)
    return BounceStep(
        horizontal.position,
        vertical.position,
        horizontal.velocity,
        vertical.velocity,
        horizontal.oversized,
        vertical.oversized,
    )


def bounce_start_position(
    x: float,
    y: float,
    bounds_width: float,
    bounds_height: float,
    item_width: float,
    item_height: float,
) -> tuple[float, float, bool, bool]:
    horizontal = bounce_axis(x, 0.0, 0.0, bounds_width, item_width)
    vertical = bounce_axis(y, 0.0, 0.0, bounds_height, item_height)
    return horizontal.position, vertical.position, horizontal.oversized, vertical.oversized


@dataclass(frozen=True)
class FrameAdvance:
    index: int
    deadline: float
    advanced: int
    skipped: int
    rebased: bool


def frame_delay_seconds(duration_ms: int, speed: float) -> float:
    speed = float(speed)
    if not math.isfinite(speed) or speed <= 0.0:
        return 9.999
    return max(0.001, normalize_frame_duration(duration_ms) / 1000.0 / speed)


def advance_frame_timeline(
    index: int,
    deadline: float,
    now: float,
    durations: list[int] | tuple[int, ...],
    speed: float,
    *,
    max_catchup: int = MAX_CATCHUP_FRAMES,
) -> FrameAdvance:
    """Advance an absolute GIF timeline and draw only the newest due frame.

    Under normal load exactly one frame advances. If the main loop was late,
    overdue frames remain accounted for against their absolute deadlines, while
    only the final due frame is rendered. Extreme stalls rebase once instead of
    causing a burst of zero-delay callbacks.
    """

    count = len(durations)
    if count <= 1:
        return FrameAdvance(max(0, min(index, count - 1)), deadline, 0, 0, False)

    index = int(index) % count
    deadline = float(deadline)
    now = float(now)
    advanced = 0
    limit = max(1, int(max_catchup))
    while deadline <= now and advanced < limit:
        index = (index + 1) % count
        deadline += frame_delay_seconds(durations[index], speed)
        advanced += 1

    rebased = deadline <= now
    if rebased:
        deadline = now + frame_delay_seconds(durations[index], speed)
    return FrameAdvance(index, deadline, advanced, max(0, advanced - 1), rebased)


def _install_frame_store_patch(module: Any) -> None:
    cls = module.FrameStore
    if getattr(cls, "_gif_player_decode_patched", False):
        return

    def decode(self: Any) -> None:
        try:
            with module.Image.open(self.path) as gif:
                total = max(1, int(getattr(gif, "n_frames", 1)))
                source_width, source_height = gif.size
                factor = min(
                    1.0,
                    module.MAX_SOURCE_DIM / float(max(source_width, source_height)),
                )
                budget = module.MEMORY_BUDGET_MB * 1024 * 1024
                estimate = total * (source_width * factor) * (source_height * factor) * 4
                if estimate > budget:
                    factor *= math.sqrt(budget / estimate)
                target_width = max(1, int(round(source_width * factor)))
                target_height = max(1, int(round(source_height * factor)))
                self.width, self.height = target_width, target_height

                first_sent = False
                resampling = getattr(module.Image, "Resampling", module.Image).LANCZOS
                for rgba, duration in iter_composited_frames(gif):
                    if self._abort:
                        return
                    if rgba.size != (target_width, target_height):
                        rgba = rgba.resize((target_width, target_height), resampling)
                    surface, buffer = cairo_surface_from_rgba(rgba, module.cairo)
                    with self._lock:
                        if self._abort:
                            return
                        self._frames.append(surface)
                        self._buffers.append(buffer)
                        self.durations.append(duration)
                    if not first_sent:
                        first_sent = True
                        module.GLib.idle_add(self._notify_first)

            with self._lock:
                self.total = len(self._frames)
                self.complete = self.total > 0
            if self.total == 0:
                raise RuntimeError("No frames in GIF")
        except Exception as exc:
            if self._abort:
                return
            with self._lock:
                have = len(self._frames)
                self.total = have
                self.complete = have > 0
            if have:
                module.log(f"Partial decode ({have} frames) fuer {self.path}: {exc}")
            else:
                self.error = str(exc)
                module.GLib.idle_add(self._notify_first)

    cls._decode = decode
    cls._gif_player_decode_patched = True


def install_runtime_patches(module: Any) -> None:
    """Install narrow runtime fixes on the loaded GTK implementation."""

    _install_frame_store_patch(module)
    cls = module.WidgetWindow
    if getattr(cls, "_gif_player_runtime_patched", False):
        return

    original_init = cls.__init__
    original_on_draw = cls._on_draw
    original_queue_redraw = cls._queue_redraw
    original_status = cls.status

    def debug(self: Any, event: str, **fields: Any) -> None:
        if not getattr(self, "_debug_timing", False):
            return
        payload = {
            "event": event,
            "mono_ns": time.monotonic_ns(),
            "widget": getattr(self, "widget_id", "?"),
            **fields,
        }
        module.log("timing " + json.dumps(payload, sort_keys=True, separators=(",", ":")))

    def patched_init(self: Any, *args: Any, **kwargs: Any) -> None:
        self._surface_phase = "initial"
        self._transition_timeout_id = None
        self._pending_hop_start = False
        self._hop_start_us = None
        self._bounce_x = None
        self._bounce_y = None
        self._debug_timing = os.environ.get("GIF_PLAYER_DEBUG_TIMING") == "1"
        self._debug_draws = 0
        self._debug_queued = 0
        self._debug_skipped = 0
        original_init(self, *args, **kwargs)
        if self._surface_phase == "initial":
            self._surface_phase = "canvas" if self._canvas_mode else "compact"

    def active_base(self: Any) -> tuple[float, float]:
        if self.bouncing and self._bounce_x is not None and self._bounce_y is not None:
            return float(self._bounce_x), float(self._bounce_y)
        return float(self.window_x), float(self.window_y)

    def patched_draw_origin(self: Any) -> tuple[float, float]:
        phase = getattr(self, "_surface_phase", "canvas" if self._canvas_mode else "compact")
        if phase in {"compact", "to-canvas", "to-compact"}:
            return 0.0, 0.0
        x, y = active_base(self)
        return x, y - float(self.hop_offset_y)

    def fully_inside(self: Any) -> bool:
        width, height = self.gif_size()
        return is_fully_inside(
            self.window_x,
            self.window_y,
            width,
            height,
            self.bounds_w,
            self.bounds_h,
        )

    def patched_wanted_canvas(self: Any) -> bool:
        return (
            (not self.locked)
            or self.bouncing
            or self.hop_active
            or self.dragging
            or not fully_inside(self)
        )

    def arm_transition_fallback(self: Any) -> None:
        def finish() -> bool:
            self._transition_timeout_id = None
            if self._surface_phase == "to-canvas":
                finish_to_canvas(self, "timeout")
            elif self._surface_phase == "to-compact":
                finish_to_compact(self, "timeout")
            return False

        self._transition_timeout_id = module.GLib.timeout_add(TRANSITION_FALLBACK_MS, finish)

    def begin_to_canvas(self: Any) -> None:
        self._surface_phase = "to-canvas"
        # Phase one expands from the old top-left margin while drawing at zero.
        # The visible global position therefore remains exactly unchanged.
        self._canvas_mode = False
        left = max(0, int(round(self.window_x)))
        top = max(0, int(round(self.window_y)))
        module.GtkLayerShell.set_margin(self, module.GtkLayerShell.Edge.LEFT, left)
        module.GtkLayerShell.set_margin(self, module.GtkLayerShell.Edge.TOP, top)
        module.GtkLayerShell.set_anchor(self, module.GtkLayerShell.Edge.RIGHT, True)
        module.GtkLayerShell.set_anchor(self, module.GtkLayerShell.Edge.BOTTOM, True)
        self.set_size_request(-1, -1)
        debug(self, "surface-to-canvas-begin", left=left, top=top)
        self._update_input_region()
        self.area.queue_draw()
        arm_transition_fallback(self)

    def finish_to_canvas(self: Any, reason: str) -> bool:
        if self._surface_phase != "to-canvas":
            return False
        self._surface_phase = "canvas"
        self._canvas_mode = True
        module.GtkLayerShell.set_margin(self, module.GtkLayerShell.Edge.LEFT, 0)
        module.GtkLayerShell.set_margin(self, module.GtkLayerShell.Edge.TOP, 0)
        module.GtkLayerShell.set_anchor(self, module.GtkLayerShell.Edge.RIGHT, True)
        module.GtkLayerShell.set_anchor(self, module.GtkLayerShell.Edge.BOTTOM, True)
        self.set_size_request(-1, -1)
        self._update_input_region()
        self.area.queue_draw()
        debug(self, "surface-to-canvas-end", reason=reason)
        if self._pending_hop_start:
            start_hop_tick(self)
        return False

    def begin_to_compact(self: Any) -> None:
        if not fully_inside(self):
            return
        self._surface_phase = "to-compact"
        self._canvas_mode = True
        left = int(round(self.window_x))
        top = int(round(self.window_y))
        module.GtkLayerShell.set_margin(self, module.GtkLayerShell.Edge.LEFT, left)
        module.GtkLayerShell.set_margin(self, module.GtkLayerShell.Edge.TOP, top)
        module.GtkLayerShell.set_anchor(self, module.GtkLayerShell.Edge.RIGHT, True)
        module.GtkLayerShell.set_anchor(self, module.GtkLayerShell.Edge.BOTTOM, True)
        self.set_size_request(-1, -1)
        self._update_input_region()
        self.area.queue_draw()
        debug(self, "surface-to-compact-begin", left=left, top=top)
        arm_transition_fallback(self)

    def finish_to_compact(self: Any, reason: str) -> bool:
        if self._surface_phase != "to-compact":
            return False
        if not fully_inside(self):
            self._surface_phase = "canvas"
            self._canvas_mode = True
            module.GtkLayerShell.set_margin(self, module.GtkLayerShell.Edge.LEFT, 0)
            module.GtkLayerShell.set_margin(self, module.GtkLayerShell.Edge.TOP, 0)
            return False
        self._surface_phase = "compact"
        self._canvas_mode = False
        module.GtkLayerShell.set_anchor(self, module.GtkLayerShell.Edge.RIGHT, False)
        module.GtkLayerShell.set_anchor(self, module.GtkLayerShell.Edge.BOTTOM, False)
        self._sync_compact_size()
        self._sync_compact_margins()
        self._update_input_region()
        self.area.queue_draw()
        debug(self, "surface-to-compact-end", reason=reason)
        return False

    def patched_apply_surface_mode(self: Any, force: bool = False) -> None:
        want_canvas = patched_wanted_canvas(self)
        phase = getattr(self, "_surface_phase", "initial")
        if not getattr(self, "_first_frame_ready", False):
            self._canvas_mode = want_canvas
            self._surface_phase = "canvas" if want_canvas else "compact"
            if want_canvas:
                module.GtkLayerShell.set_margin(self, module.GtkLayerShell.Edge.LEFT, 0)
                module.GtkLayerShell.set_margin(self, module.GtkLayerShell.Edge.TOP, 0)
                module.GtkLayerShell.set_anchor(self, module.GtkLayerShell.Edge.RIGHT, True)
                module.GtkLayerShell.set_anchor(self, module.GtkLayerShell.Edge.BOTTOM, True)
                self.set_size_request(-1, -1)
            else:
                module.GtkLayerShell.set_anchor(self, module.GtkLayerShell.Edge.RIGHT, False)
                module.GtkLayerShell.set_anchor(self, module.GtkLayerShell.Edge.BOTTOM, False)
                self._sync_compact_size()
                self._sync_compact_margins()
            self._update_input_region()
            self.area.queue_draw()
            return

        if want_canvas:
            if phase in {"canvas", "to-canvas"} and not force:
                return
            if phase == "to-compact":
                self._surface_phase = "canvas"
                self._canvas_mode = True
                module.GtkLayerShell.set_margin(self, module.GtkLayerShell.Edge.LEFT, 0)
                module.GtkLayerShell.set_margin(self, module.GtkLayerShell.Edge.TOP, 0)
                return
            begin_to_canvas(self)
        else:
            if phase in {"compact", "to-compact"} and not force:
                return
            if phase == "to-canvas":
                finish_to_canvas(self, "reversed")
            begin_to_compact(self)

    def patched_on_size_allocate(self: Any, widget: Any, allocation: Any) -> None:
        debug(
            self,
            "size-allocate",
            width=int(allocation.width),
            height=int(allocation.height),
            phase=self._surface_phase,
        )
        if self._surface_phase == "to-canvas":
            module.GLib.idle_add(finish_to_canvas, self, "size-allocate")
        elif self._surface_phase == "to-compact":
            module.GLib.idle_add(finish_to_compact, self, "size-allocate")
        elif self._surface_phase == "canvas" and self._canvas_mode:
            if allocation.width >= int(self.mon_w * 0.7) and allocation.height >= int(self.mon_h * 0.7):
                self.bounds_w = int(allocation.width)
                self.bounds_h = int(allocation.height)
        self._update_input_region()

    def patched_set_pos(self: Any, x: float, y: float, clamp: bool = False) -> None:
        old = self._gif_rect_padded()
        self.window_x, self.window_y = manual_position(x, y)
        self._state_dirty = True
        if self._canvas_mode or self._surface_phase in {"canvas", "to-compact"}:
            self._queue_redraw(old)
            if not self.locked:
                self._update_input_region()
        else:
            self._sync_compact_margins()
        if self.locked and not self.bouncing and not self.hop_active:
            self._apply_surface_mode()
        debug(self, "position", x=self.window_x, y=self.window_y, clamp_requested=bool(clamp))

    def patched_snap_axis(value: float, size: float, bound: float) -> float:
        edge = float(module.EDGE_SNAP)
        maximum = float(bound) - float(size)
        if 0.0 <= value <= edge:
            return 0.0
        if maximum >= 0.0 and maximum - edge <= value <= maximum:
            return maximum
        center = maximum / 2.0
        if 0.0 <= value <= maximum and abs(value - center) <= edge:
            return center
        return value

    def patched_set_scale(self: Any, scale: float) -> dict[str, Any]:
        scale = max(0.1, min(float(scale), 5.0))
        if abs(scale - self.scale) < 1e-6:
            return self.status()
        old_rect = self._gif_rect_padded()
        old_width, old_height = self.gif_size()
        base_x, base_y = active_base(self)
        center_x = base_x + old_width / 2.0
        center_y = base_y + old_height / 2.0
        self.scale = scale
        new_width, new_height = self.gif_size()
        new_x = center_x - new_width / 2.0
        new_y = center_y - new_height / 2.0
        if self.bouncing:
            start_x, start_y, oversized_x, oversized_y = bounce_start_position(
                new_x,
                new_y,
                self.bounds_w,
                self.bounds_h,
                new_width,
                new_height,
            )
            self._bounce_x, self._bounce_y = start_x, start_y
            if oversized_x:
                self.bounce_vx = 0.0
            if oversized_y:
                self.bounce_vy = 0.0
        else:
            self.window_x, self.window_y = new_x, new_y
        self._state_dirty = True
        self._apply_surface_mode()
        self._queue_redraw(old_rect)
        if not self.locked:
            self._update_input_region()
        debug(self, "scale", scale=self.scale, x=new_x, y=new_y)
        return self.status()

    def patched_queue_redraw(self: Any, old_rect: Any = None) -> None:
        if self._debug_timing:
            self._debug_queued += 1
            debug(self, "queue-draw", old=old_rect, new=self._gif_rect_padded(), count=self._debug_queued)
        original_queue_redraw(self, old_rect)

    def patched_on_draw(self: Any, area: Any, context: Any) -> bool:
        if self._debug_timing:
            self._debug_draws += 1
            allocation = area.get_allocation()
            debug(
                self,
                "draw",
                draw=self._debug_draws,
                frame=int(self.frame_index),
                origin=self._draw_origin(),
                allocation=[int(allocation.width), int(allocation.height)],
                phase=self._surface_phase,
                opacity=float(self.opacity),
            )
        previous_canvas_mode = self._canvas_mode
        if self._surface_phase in {"to-canvas", "to-compact"}:
            # The old callback intentionally emitted a transparent transition
            # frame. Position-preserving phases make that guard unnecessary.
            self._canvas_mode = False
        try:
            return original_on_draw(self, area, context)
        finally:
            self._canvas_mode = previous_canvas_mode

    def start_hop_tick(self: Any) -> None:
        if not self._pending_hop_start or not self.hop_active:
            return
        self._pending_hop_start = False
        self._hop_last_us = None
        self._hop_start_us = None
        if self._hop_tick_id is None:
            self._hop_tick_id = self.area.add_tick_callback(self._hop_tick)
        debug(self, "jump-ready", x=self.window_x, y=self.window_y, offset=0.0)

    def patched_hop(self: Any) -> None:
        if self.hop_active or self._pending_hop_start:
            return
        self.hop_active = True
        self.hop_t = 0.0
        self.hop_offset_y = 0.0
        self._pending_hop_start = True
        debug(self, "jump-command", x=self.window_x, y=self.window_y)
        self._apply_surface_mode()
        if self._surface_phase == "canvas" and self._canvas_mode:
            start_hop_tick(self)

    def patched_cancel_hop(self: Any) -> None:
        if self._hop_tick_id is not None:
            try:
                self.area.remove_tick_callback(self._hop_tick_id)
            except Exception:
                pass
        self._hop_tick_id = None
        self._pending_hop_start = False
        self._hop_start_us = None
        self.hop_active = False
        self.hop_t = 0.0
        self.hop_offset_y = 0.0
        debug(self, "jump-cancel")

    def patched_hop_tick(self: Any, widget: Any, frame_clock: Any) -> Any:
        if not self.hop_active:
            self._hop_tick_id = None
            return module.GLib.SOURCE_REMOVE
        now_us = int(frame_clock.get_frame_time())
        if self._hop_start_us is None:
            self._hop_start_us = now_us
            self._hop_last_us = now_us
            self.hop_t = 0.0
            self.hop_offset_y = 0.0
            self._queue_redraw()
            debug(self, "jump-frame", progress=0.0, offset=0.0)
            return module.GLib.SOURCE_CONTINUE

        elapsed = max(0.0, (now_us - self._hop_start_us) / 1_000_000.0)
        progress = min(1.0, elapsed / float(module.HOP_DURATION))
        old = self._gif_rect_padded()
        self.hop_t = progress * math.pi
        self.hop_offset_y = jump_offset(progress, module.HOP_HEIGHT)
        self._queue_redraw(old)
        debug(self, "jump-frame", progress=progress, offset=self.hop_offset_y)
        if progress >= 1.0:
            self._hop_tick_id = None
            self.hop_active = False
            self.hop_t = math.pi
            self.hop_offset_y = 0.0
            self._queue_redraw(old)
            debug(self, "jump-end", x=self.window_x, y=self.window_y, offset=0.0)
            self._apply_surface_mode()
            return module.GLib.SOURCE_REMOVE
        return module.GLib.SOURCE_CONTINUE

    def patched_start_bounce(self: Any) -> None:
        if self.bouncing:
            return
        width, height = self.gif_size()
        start_x, start_y, oversized_x, oversized_y = bounce_start_position(
            self.window_x,
            self.window_y,
            self.bounds_w,
            self.bounds_h,
            width,
            height,
        )
        quadrants = [0.5, math.pi - 0.5, math.pi + 0.5, 2 * math.pi - 0.5]
        angle = module.random.choice(quadrants) + module.random.uniform(-0.3, 0.3)
        self.bounce_vx = 0.0 if oversized_x else math.cos(angle) * module.BOUNCE_SPEED
        self.bounce_vy = 0.0 if oversized_y else math.sin(angle) * module.BOUNCE_SPEED
        self._bounce_x = start_x
        self._bounce_y = start_y
        self.bouncing = True
        self._state_dirty = True
        self._apply_surface_mode()
        self._bounce_last_us = None
        if self._bounce_tick_id is None:
            self._bounce_tick_id = self.area.add_tick_callback(self._bounce_tick)
        debug(
            self,
            "bounce-start",
            x=start_x,
            y=start_y,
            oversized_x=oversized_x,
            oversized_y=oversized_y,
        )

    def patched_stop_bounce(self: Any) -> None:
        if self.bouncing and self._bounce_x is not None and self._bounce_y is not None:
            # Commit the visible position so stopping remains continuous.
            self.window_x = float(self._bounce_x)
            self.window_y = float(self._bounce_y)
        self.bouncing = False
        self._bounce_x = None
        self._bounce_y = None
        self._state_dirty = True
        if self._bounce_tick_id is not None:
            try:
                self.area.remove_tick_callback(self._bounce_tick_id)
            except Exception:
                pass
        self._bounce_tick_id = None
        self._apply_surface_mode()
        self._queue_redraw()
        debug(self, "bounce-stop", x=self.window_x, y=self.window_y)

    def patched_bounce_tick(self: Any, widget: Any, frame_clock: Any) -> Any:
        if not self.bouncing:
            self._bounce_tick_id = None
            return module.GLib.SOURCE_REMOVE
        now_us = int(frame_clock.get_frame_time())
        if self._bounce_last_us is None:
            self._bounce_last_us = now_us
            return module.GLib.SOURCE_CONTINUE
        dt = min(0.05, max(0.0, (now_us - self._bounce_last_us) / 1_000_000.0))
        self._bounce_last_us = now_us
        width, height = self.gif_size()
        old = self._gif_rect_padded()
        step = bounce_step(
            self._bounce_x if self._bounce_x is not None else self.window_x,
            self._bounce_y if self._bounce_y is not None else self.window_y,
            self.bounce_vx,
            self.bounce_vy,
            dt,
            self.bounds_w,
            self.bounds_h,
            width,
            height,
        )
        self._bounce_x, self._bounce_y = step.x, step.y
        self.bounce_vx, self.bounce_vy = step.vx, step.vy
        self._state_dirty = True
        self._queue_redraw(old)
        return module.GLib.SOURCE_CONTINUE

    def patched_arm_frame_timer(self: Any) -> None:
        delay = self._frame_deadline - time.monotonic()
        if delay < -0.25:
            self._frame_deadline = time.monotonic()
            delay = 0.0
        milliseconds = 0 if delay <= 0.0 else max(1, int(math.ceil(delay * 1000.0)))
        self._frame_timer_id = module.GLib.timeout_add(milliseconds, self._advance_frame)

    def patched_advance_frame(self: Any) -> bool:
        self._frame_timer_id = None
        if self._closed or self.paused or not self._first_frame_ready:
            return False
        count = self.store.count()
        if count <= 1 and self.store.complete:
            return False
        if not self.store.complete and self.frame_index + 1 >= count:
            self._frame_timer_id = module.GLib.timeout_add(15, self._advance_frame)
            return False

        durations: list[int] = []
        for index in range(count):
            _surface, duration = self.store.get(index)
            durations.append(duration)
        result = advance_frame_timeline(
            self.frame_index,
            self._frame_deadline,
            time.monotonic(),
            durations,
            self.speed,
        )
        if result.advanced <= 0:
            self._frame_deadline = result.deadline
            self._arm_frame_timer()
            return False
        self.frame_index = result.index
        self._frame_deadline = result.deadline
        self._debug_skipped += result.skipped
        self._queue_redraw()
        debug(
            self,
            "frame-advance",
            frame=self.frame_index,
            advanced=result.advanced,
            skipped=result.skipped,
            skipped_total=self._debug_skipped,
            rebased=result.rebased,
            deadline=self._frame_deadline,
        )
        self._arm_frame_timer()
        return False

    def patched_status(self: Any) -> dict[str, Any]:
        result = original_status(self)
        draw_x, draw_y = active_base(self)
        result["x"] = int(draw_x)
        result["y"] = int(draw_y)
        result["base_position"] = [int(self.window_x), int(self.window_y)]
        result["surface_mode"] = self._surface_phase
        return result

    def patched_save_now(self: Any) -> None:
        if not self.is_primary:
            return
        draw_x, draw_y = active_base(self)
        module.STATE.put(
            self.state_key,
            {
                "x": draw_x,
                "y": draw_y,
                "scale": self.scale,
                "opacity": self.opacity,
                "flip_h": self.flip_h,
                "flip_v": self.flip_v,
                "speed": self.speed,
                "bouncing": self.bouncing,
                "jumping": self.jumping,
                "jump_rate": self.jump_rate,
            },
        )

    cls.__init__ = patched_init
    cls._draw_origin = patched_draw_origin
    cls._wanted_canvas = patched_wanted_canvas
    cls._apply_surface_mode = patched_apply_surface_mode
    cls._on_size_allocate = patched_on_size_allocate
    cls._set_pos = patched_set_pos
    cls._snap_axis = staticmethod(patched_snap_axis)
    cls.set_scale = patched_set_scale
    cls._queue_redraw = patched_queue_redraw
    cls._on_draw = patched_on_draw
    cls.hop = patched_hop
    cls._cancel_hop = patched_cancel_hop
    cls._hop_tick = patched_hop_tick
    cls.start_bounce = patched_start_bounce
    cls.stop_bounce = patched_stop_bounce
    cls._bounce_tick = patched_bounce_tick
    cls._arm_frame_timer = patched_arm_frame_timer
    cls._advance_frame = patched_advance_frame
    cls.status = patched_status
    cls._save_now = patched_save_now
    cls._gif_player_runtime_patched = True
