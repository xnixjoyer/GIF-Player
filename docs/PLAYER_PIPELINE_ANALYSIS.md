# Player pipeline analysis and stability work

This report describes the player implementation at the repository state based on
`main` commit `f549822a69d2444151e6cc398ff288fbbda66bb8`, the defects found, the
changes on branch `player-pipeline-stability`, measurements that were actually
executed, and tests that still require a real Niri session.

## 1. Architecture

```text
 gif-player / gif-picker / gif-control
                 │
                 ├── XDG paths and package bootstrap
                 │     ├── gif_player_paths.py
                 │     ├── gif_player_bootstrap.py
                 │     └── gif_player_runtime.py
                 │
                 └── one gif-player daemon process
                       ├── Gio.SocketService / JSON IPC v2
                       ├── WidgetManager
                       │     └── WidgetWindow × N
                       │           ├── GTK3 DrawingArea
                       │           ├── GtkLayerShell surface
                       │           ├── compact mode
                       │           └── monitor-local canvas mode
                       └── FrameStoreRegistry
                             └── FrameStore per real GIF path
                                   ├── Pillow decode thread
                                   ├── Cairo surfaces
                                   └── retained byte buffers
```

The existing architecture is retained:

- GTK3, GtkLayerShell, Cairo and Pillow remain in use.
- One supervisor daemon owns every GTK window.
- IPC remains newline-delimited JSON protocol v2.
- Multiple instances and profile/state compatibility remain intact.
- Identical real GIF paths still share one decoded frame store.
- Dragging still moves the image inside a stable canvas instead of moving the
  Wayland surface on every pointer event.

`gif_player_runtime.py` contains pure logic plus narrow runtime corrections. It
is activated by `configure_main()` after `gif-script.py` is loaded. This allows
geometry, timing and decode behavior to be tested without importing GTK in unit
tests while avoiding a rewrite of the established player.

## 2. Complete playback pipeline

### 2.1 File selection and daemon spawn

1. CLI or picker resolves a GIF path.
2. `ensure_daemon()` starts the packaged `gif-player daemon` wrapper when the
   socket is not reachable.
3. IPC `spawn` reaches `WidgetManager.spawn()`.
4. The manager allocates `name`, `name-2`, `name-3`, and so on.
5. A `WidgetWindow` acquires a `FrameStore` by canonical real path.

### 2.2 GIF decoding

The decode thread now performs this sequence:

1. Open the GIF once with Pillow.
2. Read logical-canvas size and frame count.
3. Calculate one decode scale from `MAX_SOURCE_DIM` and the memory budget.
4. Seek each frame explicitly.
5. Convert the current Pillow logical canvas to an independent RGBA copy.
6. Normalize the frame duration.
7. Resize once when the decode scale requires it.
8. Convert straight RGBA to premultiplied little-endian BGRA for Cairo ARGB32.
9. Create a Cairo image surface backed by a retained `bytearray`.
10. Append surface, buffer and duration under the frame-store lock.
11. Notify the GTK main loop after frame zero becomes available.

Pillow's GIF seek operation materializes the composited logical canvas. Tests
cover transparent delta frames, disposal 2, disposal 3 and different local
palettes. The explicit RGBA copy is important: a later seek cannot mutate a
previously stored frame.

A missing or non-positive duration becomes 100 ms. A positive duration below
20 ms becomes 20 ms. The previous implementation replaced every value below
20 ms with 80 ms, which changed a valid 10 ms GIF by a factor of eight. The new
floor preserves fast animation while avoiding a 0 ms callback loop.

### 2.3 Frame storage and sharing

A `FrameStore` retains both the Cairo surface and its underlying byte buffer.
This is required because `ImageSurface.create_for_data()` does not copy pixel
data. Surface and buffer lists are appended together while holding the same
lock. Readers obtain a surface and duration under that lock.

The first frame may play while the remaining file is decoded. If playback
reaches the currently decoded tail, the player holds the last valid frame and
retries after 15 ms. It does not clear the surface or expose an incomplete
frame. If a corrupt tail is encountered after valid frames, the valid prefix is
kept. If no frame can be decoded, the widget closes with a logged error.

The registry reference count remains per canonical real path. Releasing the
last widget aborts an in-progress decode and drops the surface and buffer lists.

### 2.4 Animation timing

The player retains a monotonic absolute deadline model:

```text
frame_deadline = previous_deadline + frame_duration / speed
```

This avoids cumulative drift from repeatedly scheduling `now + duration`.
Timer arming now rounds a positive delay upward to at least 1 ms, avoiding an
early 0 ms wake-up caused by integer truncation.

When the GTK main loop is late, the old implementation advanced one frame and
could then schedule several immediate callbacks. That rendered a visible burst
of stale frames. The new scheduler advances the absolute timeline through all
overdue durations, queues one draw for the newest due frame, and records the
intermediate frames as skipped. Catch-up is capped at eight frame advances; an
extreme stall rebases once instead of producing an unbounded callback burst.

Normal playback does not skip: a callback at its deadline advances exactly one
frame. Pause and resume still restart the current frame from `now`; changing
speed also restarts the current frame deadline, avoiding a large discontinuity.

### 2.5 Cairo rendering

The established draw path is retained:

1. GTK provides a clipped Cairo context for the damaged region.
2. `OPERATOR_SOURCE` clears that clip to transparent.
3. The current valid Cairo frame is selected.
4. Translation establishes the draw origin.
5. Horizontal and vertical flips are applied.
6. Scale maps decoded dimensions to the integer display dimensions.
7. `FILTER_GOOD` is used for the source pattern.
8. Opacity is applied with `paint_with_alpha()` when needed.
9. The edit outline is drawn only while unlocked.

A transparent clear is correct when clear and image paint occur in the same draw
callback. It was not the fundamental flicker cause. The defect was an early
return after the clear and before the image paint.

`FILTER_BEST`, permanent pre-scaling and a per-scale frame cache were rejected:
they increase CPU or memory substantially and do not address the transition
bug. Subpixel motion is retained for hop and bounce; static compact margins are
rounded to integer pixels.

## 3. Coordinate systems

All stored positions are monitor-local logical GTK coordinates.

```text
base_x, base_y       persistent manual position
bounce_x, bounce_y   temporary visible base while bounce is active
jump_offset_y        temporary vertical animation offset
draw_x               active_base_x
draw_y               active_base_y - jump_offset_y
```

- Compact surface coordinates start at `(0, 0)` because the Layer Shell margin
  carries the global monitor-local position.
- Stable canvas coordinates use the monitor-local base position directly.
- Pointer coordinates during dragging are canvas coordinates.
- The drag formula remains:

```text
new_base = drag_origin + (pointer_now - pointer_at_press)
```

No monitor clamp is applied to manual movement. Negative values, values beyond
right/bottom, and completely invisible positions are valid and persist.

Edge snapping now applies only while approaching an edge from inside. A pointer
that has crossed an edge is not snapped back to it. Center snapping remains
inside the valid interval.

## 4. Proven jump-flicker cause

The original `_on_draw()` did the following in order:

1. Clear the damaged area with transparent `OPERATOR_SOURCE`.
2. Detect that Compact-to-Canvas allocation was still GIF-sized.
3. Intentionally return without painting the GIF.

The source comment explicitly said that one empty frame was preferred to a
briefly misplaced GIF. Therefore the reported disappearance was deterministic,
not a speculative Pillow, alpha, frame-store or opacity race.

The relevant behavior was:

```text
transparent clear
→ Compact-to-Canvas guard
→ return False
→ no image paint for that draw
```

This explains why it appeared immediately before every hop: `hop()` set
`hop_active`, `_wanted_canvas()` changed from false to true, and the surface
mode switch triggered exactly that guarded draw.

## 5. Jump fix: position-preserving two-phase transition

The fix removes the need for an empty transition frame.

### Compact to canvas

Phase 1:

- Keep left/top margins at the existing base position.
- Add right/bottom anchors.
- Request an expanded surface.
- Keep logical compact drawing and draw the current frame at `(0, 0)`.

The surface therefore grows from the old top-left point and the displayed GIF
stays on the same global pixels.

Phase 2, after `size-allocate`:

- Set left/top margins to zero.
- Mark the surface as a real canvas.
- Draw the same frame at `(base_x, base_y)`.

Changing surface origin from `(base_x, base_y)` to `(0, 0)` and changing draw
origin from `(0, 0)` to `(base_x, base_y)` cancel each other. The first hop tick
is not installed until this phase is ready. Its progress and offset are exactly
zero.

A 120 ms fallback finishes a transition only if a compositor does not emit the
expected allocation notification. It does not run during stable operation.

### Canvas to compact

The reverse transition first moves the still-expanded surface origin to the
base margins while drawing at `(0, 0)`, then removes right/bottom anchors and
shrinks to GIF size. A fully inside locked widget therefore returns to compact
mode without changing its visible position.

The old intentional blank-frame guard remains in the legacy source for source
compatibility, but the runtime wrapper disables only that guard while a new
position-preserving transition phase is active. The established clear,
transform, filter, opacity and outline code still runs.

### Jump curve

Hop progress is derived from absolute GTK frame-clock time:

```text
progress = clamp((frame_time - hop_start_time) / duration, 0, 1)
offset = height * sin(pi * progress)
```

This gives exact zero at start and landing, a continuous first movement, and no
accumulated `dt` integration error. Normal GIF frame animation continues on its
independent deadline timeline throughout the hop.

## 6. Free offscreen positioning

Manual `_set_pos`, direct X/Y control, `move-by`, dragging and scale-center
preservation no longer call the monitor clamp. Positions can be negative or
larger than the monitor dimensions.

A compact Layer Shell surface with negative or beyond-edge margins is not a
portable representation across wlroots compositors. Therefore a locked widget
uses compact mode only when its entire scaled rectangle is inside the selected
monitor. A partially or completely offscreen locked widget stays in canvas
mode with an empty input region. This preserves exact clipping and remains
click-through.

Once `reset`, `corner center`, direct X/Y IPC, or the control panel places the
rectangle fully inside again, the position-preserving reverse transition can
return it to compact mode.

Recovery paths remain:

```console
gif-player ipc ID reset
gif-player ipc ID corner center
gif-player ipc ID move X Y
```

## 7. Bounce boundaries

Bounce no longer reuses the manual clamp function.

- Manual position remains unrestricted.
- Bounce startup maps the visible position to a valid bounce interval.
- Bounce uses separate `_bounce_x` and `_bounce_y` coordinates while active.
- The draw origin uses the bounce coordinates without modifying the manual base
  on every tick.
- Stopping bounce commits the current visible bounce position once, avoiding a
  visual jump at the stop boundary.

Reflection uses a triangular-wave modulo calculation rather than single-edge
`if` statements. It remains bounded even when a large `dt` crosses multiple
edges.

If the scaled GIF is larger than the monitor on one axis, a valid fully inside
bounce interval does not exist. The selected fallback is:

- center the oversized item on that axis,
- set that velocity component to zero,
- continue normal bounce on the other axis when it fits.

This avoids negative maximum bounds, repeated sign flips, NaNs and high-frequency
edge jitter. It does not claim that an oversized image can be fully visible,
which is mathematically impossible.

## 8. Instrumentation

Set:

```console
GIF_PLAYER_DEBUG_TIMING=1 gif-player daemon
```

The daemon log then receives compact JSON timing events with monotonic
nanoseconds. Events include:

- `jump-command`, `jump-ready`, `jump-frame`, `jump-end`,
- `surface-to-canvas-begin/end`,
- `surface-to-compact-begin/end`,
- `size-allocate`,
- `position`, `scale`,
- `queue-draw`, `draw`,
- `frame-advance`, skipped-frame count and rebases,
- `bounce-start`, `bounce-stop`.

Instrumentation is disabled by default. The normal path performs only one
boolean check in wrapped draw and redraw methods.

## 9. Evaluated ideas

| Idea | Problem addressed | Expected benefit | Measurement/result | Risk | Decision |
|---|---|---:|---|---:|---|
| Keep deliberate empty transition frame | Wrong-position transient | Avoids one misplaced frame | It deterministically creates the reported disappearance | High visual cost | Removed from active transition path |
| Two-phase margin/anchor transition | Compact/Canvas geometry race | High | Coordinate equivalence proven; pixel start test added | Medium compositor dependency | Implemented |
| Permanent full-monitor canvas | All mode-switch races | High | Would avoid transitions but keeps large surfaces permanently | Medium CPU/compositor cost | Rejected |
| Two GTK windows per widget | Atomic cross-fade/snapshot | High | No reliable test environment; doubles surface lifecycle | High | Rejected |
| Move compact Layer Shell margin every hop tick | Avoid resize | Medium | Reintroduces compositor-driven motion latency | High on Wayland | Rejected |
| Frame-clock absolute hop progress | Integration drift | High | Endpoint and continuity tests pass | Low | Implemented |
| GLib relative per-frame timer | Simple GIF timing | Low | Existing absolute deadlines are more drift resistant | Low | Rejected |
| Absolute GIF deadlines | Long-term timing drift | High | Existing model retained | Low | Retained |
| Render every overdue frame rapidly | Preserve all frames | Negative visually | Produces catch-up bursts after stalls | Medium | Replaced |
| Controlled overdue-frame skipping | Main-loop stalls | High | 100 ms synthetic late case advances 6, skips 5 draws, next deadline remains future | Low/medium | Implemented |
| Shared global scheduler | Timer wakeups for many widgets | Possible medium | Requires broad lifecycle rewrite and synchronization policy | High | Experimental only |
| `FILTER_BEST` | Downscale quality | Small | More expensive; no transition benefit | Medium CPU | Rejected |
| `FILTER_NEAREST` globally | Pixel-art sharpness | Mixed | Damages normal photographic/anime GIF scaling | Low | Rejected as global default |
| Per-scale pre-render cache | Repeated Cairo scaling | Medium | Multiplies memory for dynamic scales and shared stores | High RAM | Rejected |
| Explicit Pillow seek + RGBA copy | Disposal/palette independence | High correctness | Disposal 2/3 and palette tests pass; 180-frame benchmark is 21.6% slower in decode only | Low runtime after decode | Implemented |
| Replace sub-20 ms delays with 80 ms | Callback load | Negative timing | Distorts 10 ms to 80 ms | High fidelity loss | Replaced with 20 ms floor |
| Free manual coordinates | Offscreen placement | High | Pure tests accept negative and beyond-bound positions | Low | Implemented |
| Negative compact margins | Offscreen locked widgets | Possible low cost | Not portable enough without compositor verification | High | Rejected |
| Locked offscreen canvas fallback | Exact clipped position | High | Geometry decision tests pass | Low/medium compositor cost only for affected widgets | Implemented |
| Single global clamp | Simplicity | Negative semantics | Conflicts with free drag and oversized bounce | High | Replaced by separate logic |
| Oversized bounce center/freeze | Invalid negative interval | High stability | Unit tests pass for one and two oversized axes | Low | Implemented |
| Full-surface clear plus same-callback paint | Stale alpha pixels | High correctness | Cairo pixel test remains non-empty and identical at jump progress zero | Low | Retained |
| Damage old and new rectangles | Movement redraw cost | High | Existing path retained | Low | Retained |

## 10. Measurements actually executed

Environment available to the analysis process:

- Python 3.13.5
- Pillow 12.2.0
- pycairo available
- no `nix` executable
- no Wayland/Niri compositor
- external `git clone` blocked by DNS, repository access performed through the
  GitHub connector

A generated 180-frame, 128×128, transparent optimized GIF was decoded five
times with each method. Median results:

| Decoder iteration | Median |
|---|---:|
| `ImageSequence.Iterator` + RGBA conversion | 26.54 ms |
| explicit seek + independent RGBA copy | 32.26 ms |
| measured decode-only overhead | 21.6% |

The overhead happens once per shared frame store and buys explicit ownership and
tested disposal behavior. It does not multiply for multiple instances of the
same GIF.

Synthetic frame-pacing result for 20 ms frames with a callback 100 ms late:

```text
advanced timeline frames: 6
intermediate draw calls skipped: 5
rebased: false
next absolute deadline: 1.120 s
```

The old model would have needed repeated immediate callbacks to show those
intermediate stale frames.

## 11. Automated tests actually executed locally

Commands:

```console
python3 -m compileall -q /tmp/runtime-work
PYTHONPATH=/tmp/runtime-work python3 -m unittest discover -s /tmp/runtime-work/tests -v
```

Result: 19 tests passed.

Covered behaviors:

- exact hop endpoints and peak,
- first-tick hop continuity,
- negative and beyond-monitor manual positions,
- fully-inside/offscreen geometry classification,
- left/right bounce reflection,
- large-`dt` reflection,
- oversized-axis center/freeze,
- independent movement on the fitting axis,
- bounce startup from a fully offscreen manual position,
- duration normalization for missing, 0, 10, 20 and 80 ms,
- absolute deadline drift behavior,
- controlled late-frame skipping,
- extreme-stall rebase,
- disposal method 2,
- disposal method 3,
- local palettes and transparency,
- corrupt-tail valid-prefix behavior,
- premultiplied BGRA channel values,
- byte-identical Cairo output before hop and at hop progress zero.

## 12. Tests not claimed as executed

The following require the GitHub Actions Nix runner or a real graphical session
and are not claimed as locally executed:

- `nix flake check`
- `nix build .#default`
- packaged CLI checks
- actual GTK mapping and allocation order
- visible Niri flicker comparison
- 60/120/144 Hz display comparison
- multi-monitor placement with negative global monitor origins
- HiDPI compositor behavior
- pointer dragging and input-region interaction on Niri

GitHub Actions is used for Nix build and display-free tests. Visual acceptance
still requires the manual checklist below.

## 13. Required Niri manual acceptance checklist

Run with debug disabled first, then repeat suspect cases with
`GIF_PLAYER_DEBUG_TIMING=1` and inspect the daemon log.

1. Start a normal GIF and verify normal playback.
2. Run repeated manual `hop` commands.
3. Enable auto-jump at 2, 5 and 10 second rates.
4. Verify no disappearance before takeoff and no disappearance at landing.
5. Test opacity 25%, 50%, 75%, 100%.
6. Test horizontal, vertical and combined flip.
7. Test scales 0.3, 0.7, 1.0, 1.5 and a scale larger than the monitor.
8. Drag partially beyond every edge.
9. Drag completely beyond the monitor.
10. Recover with `corner center` and `reset`.
11. Lock while partially outside and verify exact clipping is preserved.
12. Unlock again and verify no position jump.
13. Save/reload state and profiles containing negative and large positions.
14. Start bounce from an offscreen position and verify it begins inside.
15. Stop bounce and verify no stop-time jump.
16. Test an oversized GIF: frozen centered oversized axis, moving fitting axis.
17. Run jump from a partially offscreen position.
18. Run multiple widgets, including multiple instances of one GIF.
19. Repeat on each monitor and on mixed scale factors.
20. Observe at 60 Hz and the highest available refresh rate.

## 14. Remaining risks and recommendations

1. The two-phase transition depends on wlroots Layer Shell applying anchor,
   margin and buffer updates coherently. The coordinate model removes the known
   blank frame, but actual Niri capture is still the final visual proof.
2. The 120 ms fallback is deliberately conservative. Debug logs should confirm
   that Niri normally finishes transitions through `size-allocate`, not timeout.
3. Explicit frame copies add measured decode cost. Because decode is shared and
   asynchronous, this is accepted; future work could benchmark direct Pillow
   disposal metadata handling without copies before attempting an optimization.
4. A global multi-widget frame scheduler may reduce timer wakeups, but it is not
   justified without profiling many simultaneous widgets and would increase
   coupling. Keep per-widget absolute deadlines for now.
5. Optional nearest-neighbor filtering could be exposed later for pixel art,
   but it should be a per-widget setting, not the default.
6. Multi-monitor hot-unplug needs a real compositor test. The current policy is
   intentionally non-aggressive: stored offscreen positions are not silently
   clamped after monitor changes.
