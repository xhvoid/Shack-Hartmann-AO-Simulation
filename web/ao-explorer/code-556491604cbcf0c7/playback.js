// One authoritative playback state and clock for both panels of the 2 m
// experiment: the main viewer (app.js) and the galaxy panel (galaxy.js).
//
// The state holds the installed case, the displayed-frame position, the
// playing flag, the presentation duration, the view mode ("instantaneous" or
// "average") and the optional loop.  Every control of either panel calls this
// module, and every change is announced to every subscriber, which renders
// from the same snapshot; so both panels always refer to the same case, the
// same recorded frame and the same mode.  There is exactly one timer.
//
// Timing: one pass replays the recorded physical interval in the selected
// duration.  The wall-clock instant of simulated time t is
// anchor + (t - t0) x slowdown, so each displayed frame is shown from its
// recorded timestamp until the next displayed timestamp (the last one until
// the end of the interval).  A timer (not requestAnimationFrame) so playback
// also advances in a throttled or background tab.  Exactly one displayed
// frame per tick: a late timer never skips a frame (review round 1, R1-F11);
// if the page falls more than the new frame's hold behind, the timeline
// restarts at that frame, so the display gets slower, never different (review
// round 2, R2-F02).  The loop repeats the same recording from frame 0.
// Nothing is interpolated.

export const MODES = ["instantaneous", "average"];

const s = {
  configured: false, times: [], interval: [0, 1], durations: [],
  caseId: null, position: 0, playing: false, duration: 0, mode: "instantaneous", loop: false,
  timer: null, anchor: 0,
};
const listeners = new Set();

const count = () => s.times.length;
const clamp = (position) => Math.max(0, Math.min(count() - 1, Math.trunc(position)));

export function holdEnd(position) { return position + 1 < count() ? s.times[position + 1] : s.interval[1]; }
export function slowdown() { return s.duration / (s.interval[1] - s.interval[0]); }

// The displayed timestamps, the physical interval and the offered durations
// come from the validated dataset metadata (manifest time_domain and playback).
export function configure({ times, interval, durations, defaultDuration, reducedMotionDuration, reducedMotion, position }) {
  halt();
  s.times = times.slice(); s.interval = interval.slice(); s.durations = durations.slice();
  s.duration = reducedMotion ? reducedMotionDuration : defaultDuration;
  s.configured = true;
  s.position = clamp(position);
  notify("configure");
}

export function snapshot() {
  return Object.freeze({
    configured: s.configured, caseId: s.caseId, position: s.position, count: count(),
    time: s.times[s.position], holdEnd: holdEnd(s.position), interval: s.interval.slice(), durations: s.durations.slice(),
    playing: s.playing, duration: s.duration, slowdown: s.configured ? slowdown() : null, mode: s.mode, loop: s.loop,
  });
}

// A subscriber is called with (snapshot, reason) after every change, and once
// at subscription when the clock is already configured.
export function subscribe(listener) {
  listeners.add(listener);
  if (s.configured) listener(snapshot(), "subscribe");
  return () => listeners.delete(listener);
}

function notify(reason) {
  const shot = snapshot();
  for (const listener of listeners) {
    // One panel's rendering failure must not stop the clock or the other panel.
    try { listener(shot, reason); } catch (error) { console.error(`playback subscriber failed on ${reason}:`, error); }
  }
}

function halt() { s.playing = false; clearTimeout(s.timer); s.timer = null; }

// The case the main viewer installed; a case change always pauses and keeps the position.
export function setCase(id) { halt(); s.caseId = id; notify("case"); }

export function pause() { halt(); notify("pause"); }

export function play() {
  if (!s.configured || s.caseId === null || s.mode !== "instantaneous") return;
  if (s.position >= count() - 1 && !s.loop) s.position = 0;
  s.playing = true;
  // The shown frame starts its full hold now.
  s.anchor = performance.now() - (s.times[s.position] - s.interval[0]) * slowdown() * 1000;
  notify("play");
  schedule();
}

export function toggle() { if (s.playing) pause(); else play(); }

export function seek(position) {
  if (!s.configured) return;
  halt();
  s.position = clamp(position);
  notify("seek");
}

export function step(delta) { seek(s.position + delta); }
export function restart() { seek(0); }

export function setDuration(seconds) {
  if (!s.durations.includes(seconds)) return;
  if (s.playing) {
    // Keep the simulated time on screen when the presentation speed changes.
    const t0 = s.interval[0];
    const now = performance.now();
    const shown = s.times[s.position];
    const simulated = Math.min(Math.max((now - s.anchor) / (slowdown() * 1000) + t0, shown), holdEnd(s.position));
    s.duration = seconds;
    s.anchor = now - (simulated - t0) * slowdown() * 1000;
    notify("duration");
    schedule();
  } else {
    s.duration = seconds;
    notify("duration");
  }
}

// The average/mean view has no timeline: entering it pauses; leaving it
// restores the shared position without starting playback.
export function setMode(mode) {
  if (!MODES.includes(mode)) return;
  if (mode === "average") halt();
  s.mode = mode;
  notify("mode");
}

export function setLoop(enabled) { s.loop = !!enabled; notify("loop"); }

function schedule() {
  clearTimeout(s.timer);
  if (!s.playing) return;
  const due = s.anchor + (holdEnd(s.position) - s.interval[0]) * slowdown() * 1000;
  s.timer = setTimeout(tick, Math.max(0, due - performance.now()));
}

function tick() {
  if (!s.playing) return;
  const t0 = s.interval[0];
  const scale = slowdown() * 1000;
  if (s.position + 1 < count()) {
    s.position += 1;
  } else if (s.loop) {
    s.anchor += (s.interval[1] - t0) * scale; // the same recording again from frame 0
    s.position = 0;
  } else {
    pause();
    return;
  }
  const now = performance.now();
  const shown = s.times[s.position];
  if (now - (s.anchor + (shown - t0) * scale) > (holdEnd(s.position) - shown) * scale) s.anchor = now - (shown - t0) * scale;
  notify("tick");
  schedule();
}
