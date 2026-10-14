# SC YuE2 ABC Helpers

ComfyUI nodes by **ShantyCircuit** for working with YuE2 ABC scores: search for a score that fits a target song length, check how long a score will play, change its tempo, and repair meter glitches.

All nodes appear under **ShantyCircuit/YuE2** in the node menu.

| Node | What it does |
|---|---|
| **SC YuE2 ABC Length Search** | Runs YuE2 Generate ABC repeatedly until it produces a score that fits your target length |
| **SC YuE2 ABC Song Length** | Reports how long a score will play, section by section |
| **SC YuE2 ABC Speed Change** | Speeds a whole score up or slows it down by a percentage |
| **SC YuE2 ABC Fix Meter** | Repairs one-bar meter glitches, such as a stray 7/8 bar in a 4/4 song |

Each node shows its results in a text box on the node itself after it runs.

## Requirements

- A recent ComfyUI with the V3 node API and the built-in YuE2 nodes (YuE2 Generate ABC and YuE2 Generate Music)
- No extra Python packages

## Installation

**ComfyUI Manager:** search for "SC YuE2 ABC Helpers" and install.

**Manually:** clone this repository into your `ComfyUI/custom_nodes` folder:

```
cd ComfyUI/custom_nodes
git clone https://github.com/ShantyCircuit/ComfyUI-SC-YuE2-ABC-Helpers
```

Then restart ComfyUI and refresh your browser (Ctrl+Shift+R).

## Nodes

### SC YuE2 ABC Length Search

Use this in place of the built-in **YuE2 Generate ABC** node. It takes the same inputs (model, style, lyrics, seed, mode, and the generation settings), generates a score, measures it, and tries the next seed until a score lands in your target range.

**Settings**

- **target_minutes / target_seconds**: the length you're aiming for.
- **upper_t_seconds / lower_t_seconds**: how far over and under the target is still accepted (10 seconds each by default). A target of 3:10 accepts 3:00 to 3:20. Set `upper_t_seconds` to 0 to make the target a hard ceiling.
- **max_attempts**: how many scores to try. **0 keeps trying until one fits**; press Cancel to stop.
- **max_tempo_change_percent**: lets the node change a near miss's tempo, up to this percentage, instead of discarding it. The direction is automatic: a score that's too long is sped up and one that's too short is slowed down, and the sign you enter doesn't matter. If the full change needed is more than allowed, the score still moves as far toward the target as it can. 0 (the default) never changes the tempo.
- **on_failure**: if no attempt fits, **stop workflow** skips the nodes that use the score (nothing renders), while **use closest** passes on the closest score anyway.
- **new_seed_each_run**: picks a random starting seed every time the workflow is queued.

**Outputs:** `abc` (the chosen score), `report` (the attempt log and a section-by-section breakdown), `seconds`, and `seed_used`.

**On the node**

- A live log updates after every attempt while the search runs.
- The node turns **green** when a score fits and **red** when none does, and returns to its normal color when the next run starts.
- If the chosen score has a meter glitch, the log says so (run SC YuE2 ABC Fix Meter to repair it).
- A **new search (random seed)** button picks a fresh starting seed.

**Seeds and reuse**

After a successful search, the seed box is set to the winning seed, so queueing the workflow again reuses that exact score. After a failed search, the seed box moves past the seeds already tried, so the next run continues the search. Scores generated during a session are remembered, so retrying a seed is instant until ComfyUI restarts.

The node also has its own run button, so you can search for a score without rendering any audio.

**Typical workflow**

1. Connect your YuE2 model, style, and lyrics, and set a target length.
2. Queue the workflow. The search runs first; once a score fits, the rest of the workflow (such as YuE2 Generate Music) renders it automatically.
3. Turn on `new_seed_each_run` to get a different song each time, or leave it off to re-render the last winning score.

### SC YuE2 ABC Song Length

Reports how long a score will play: total length, number of bars, bars without vocals, tempo, and a numbered section-by-section table in the `report` output. It warns if the score switches meter partway through.

**Outputs:** `report`, `seconds`, `bars`. It also has a run button for quick checks without rendering audio.

### SC YuE2 ABC Speed Change

Speeds up (positive percent) or slows down (negative percent) a whole score by scaling its tempo, from -200 to +200. Speed-ups and slow-downs mirror each other:

| speed_percent | Tempo |
|---|---|
| +200 | 3x (three times as fast) |
| +100 | 2x (twice as fast) |
| +10 | 1.1x |
| -10 | about 0.91x |
| -100 | 0.5x (half speed) |
| -200 | about 0.33x (one third of the speed) |

Notes and bars are unchanged. The node shows the tempo change and the new length.

**Outputs:** `abc`, `report`, `seconds`.

### SC YuE2 ABC Fix Meter

YuE2 Generate ABC occasionally writes a single bar in a different meter, such as one 7/8 bar in a 4/4 song, which can cause a rhythmic hiccup. This node repairs those bars:

- A **short** bar gets a rest added at its start, so pickup notes at the end stay in place.
- A **long** bar has the extra time trimmed from its rests, so no notes are lost.

A glitch is only repaired if every voice's bar can be fixed, keeping the voices lined up; otherwise it's left alone and reported. Scores without glitches pass through unchanged.

**Outputs:** `abc`, `report`.

## Good to know

**YuE2 uses one tempo for the whole song.** It ignores tempo changes written partway through a score, so a song can't be made to speed up or slow down section by section through the score. That's why SC YuE2 ABC Speed Change scales the tempo of the entire song.

## Troubleshooting

If the text boxes, colors, or the new-search button don't appear, make sure the `js` folder was installed alongside `__init__.py`, then refresh the browser with Ctrl+Shift+R. Browsers cache ComfyUI's scripts aggressively. If something still doesn't work, the browser console (F12) or the ComfyUI console usually shows why; please include those messages when opening an issue.
