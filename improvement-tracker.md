# Cadre Player Improvement Tracker

This file keeps the implementation order and status for the playback and UI fixes we discussed.

## Current Order

1. Playlist refresh stability and lighter playlist feel
2. Show title bar on top hover while fullscreen
3. Remove fullscreen transition flicker / double resize feel
4. Keep black background during file switches until next media is ready
5. Add ZIP/RAR playback workflow without full extraction
6. Reveal playlist during drag and drop for easier target selection

## Progress

### 1. Playlist refresh stability and lighter playlist feel

Status: Done

Goals:
- Keep playlist scroll position after reorder, sort, remove, and refresh-heavy actions
- Stop forcing the playlist to jump to the current row unless playback actually changes
- Preserve selection and current focus across playlist rebuilds where possible
- Reduce some of the playlist panel visual heaviness with small, low-risk tweaks

Notes:
- Main code paths: `playlist.py`, `player_window.py`, `ui/widgets.py`, `ui/styles.py`

### 2. Fullscreen title bar hover

Status: Done

Goals:
- Show the title bar when the cursor reaches the top edge in fullscreen
- Keep existing auto-hide behavior

### 3. Fullscreen flicker

Status: Done

Goals:
- Make fullscreen enter/exit feel like a single transition
- Avoid redundant resize and overlay churn during the switch

Notes:
- Residual effect: a very small last-moment settle may still be visible depending on Qt/mpv surface timing, but the major double-step resize and transparent flash are resolved

### 4. Black hold frame during media switches

Status: Done

Goals:
- Prevent transparent flashes while a file is unloading/loading
- Keep a black fill visible until the next frame is ready

Notes:
- Black cover now stays visible through track switches and clears only when playback shows ready-state signals or hits a short safe fallback

### 5. Archive playback

Status: In progress

Goals:
- Support opening media from `.zip` / `.rar` archives
- Prefer direct or selective playback flows instead of full extraction

Notes:
- ZIP archives now expand into one playlist item per playable entry and extract only the active item to a managed temp location
- Managed temp extraction is cleaned up when playback switches away or the app closes
- RAR archives now use a `tar`/`bsdtar` backend for entry listing and on-demand extraction
- Portable build direction: prefer bundled backend in app folder or `vendor/`, with system backend only as fallback during development

### 6. Drag and drop playlist reveal

Status: Done

Goals:
- Show the playlist automatically during drag and drop
- Make the drop target easier to hit and understand

## Extra Quality Items

- Done: Reduce timer-driven UI work where safe, especially repeated hover and playback polling paths
- No additional extras currently planned
