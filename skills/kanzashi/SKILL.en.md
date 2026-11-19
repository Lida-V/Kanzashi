# Kanzashi: working with generated hair strand by strand

English version of [SKILL.md](SKILL.md). Agents working in English read this file.

Kanzashi is a Blender add-on. It splits a fused hair mesh into strands (one colour and one wire per strand), lets the split be fixed by painting colours, bends strands by their wires, and makes a UV map with one island per strand.
This skill says **when and in what order an agent uses it, and where it stops to ask the user**. The code is described in [README.en.md](../../README.en.md).

`<repo>` below is the place of this repository (two folders above this file).

## When to use it

- The hair is one mesh (or a few) fused together, and strands cannot be selected, bent or painted one by one.
- The user asks to fix the flow of the hair, or to move strands out of an arm or the body.
- A clean UV per strand is needed before the hair texture is made again.

### Place in the pipeline (a rule)

**Do it at the stage where the head and the hair have been split into separate parts, before the textures are redone.** The order is:

1. Split the head and the hair into parts (the shape and place of the hair are settled here too)
2. Kanzashi (detecting strands, repainting, bending, checking for buried strands, the UV per strand)
3. Redo the hair texture

- When the head and the hair are still one mesh, split them first. The detection puts every face of the mesh it is given into some strand, so faces of the face or the scalp left in the hair become strands too.
- Done after the textures were redone, it changes the UV and the texturing has to be done again. When the order is reversed, tell the user in step 0 and decide together.
- The detection cuts the mesh along the strand borders (the vertex count grows), so do it before rigging and shape keys when you can. It also runs on rigged hair; then move the bones after the detection and check that the hair still follows the body.

Do not use it when the hair is already separate strand parts, when it is made of hair cards only, or when Blender is older than 5.3.

## Rules

- **Never change the original file.** The scripts do not save the opened file; the result goes to a new file. They stop when the output exists. Use a new output name every time.
- **Do not detect again on a file the user has repainted or bent.** `kanzashi_run.py` keeps the strands of a hair that is already detected. Use `--redetect` only when the user says "start over".
- **Install or update the add-on only with the user's permission.**
- Do not call it done on numbers alone. Whether the split is good is decided by the user looking at the pictures.
- Painting strand colours is done by the user in Blender. The agent does not paint for them (which face belongs to which strand is a visual judgement).
- Bending wires is the user's work too, as a rule. The agent moves wires only to fix strands inside the body, after stating its plan and being told "fix them by the AI's plan", and has the result confirmed with pictures (step 5).
- **Do not split, join or unwrap again a hair that has the strand UV, with any other tool or skill.** Splitting into parts, separating by material or by loose parts, joining, Smart UV or a new unwrap all break the strand UV. Kanzashi marks a hair whose UV it made (the object property `kanzashi_uv_lock`). Before and after another step touches the hair, run the check below. With exit code 1 (`split`, `changed` = vertices or faces differ, `uv_changed`, `uv_missing`) do not use the result; tell the user. If the hair must be split into parts, do it before Kanzashi (the place in the pipeline). If a marked hair really has to be split, ask the user, and make the strand UV again afterwards.

```bash
blender -b model.blend --python <repo>/scripts/kanzashi_guard.py -- --report guard.json
```

## The steps, and where to ask the user

★ marks a stop to ask the user. Ask one thing at a time, with a picture, as a choice.

### 0. Prepare

1. Find Blender and check its version (5.3 or later).
2. Find the file and the names of the hair meshes. Meshes whose name or material names contain hair, bangs and the like are taken automatically. If an ornament might be taken, or the hair missed, name them with `--hair NAME`.
3. Check the place in the pipeline (see above): is the hair a mesh of its own, apart from the head, and has the hair texture already been redone? Look at the file and at the production notes.

★ When the head and the hair are not split: say "the head and the hair have to be split into parts first" and do not start the detection until that is done.
★ When the hair texture has already been redone: say "making the strand UV means the redone texture cannot be used as it is" and ask: (a) transfer the current look to the new UV (the swap of step 6; fine detail changes a little), (b) redo the texture after Kanzashi, (c) stop.

4. Check whether the add-on is installed.

```bash
python <repo>/tools/install_addon.py --check
```

★ When it is missing or older: ask "May I install the Kanzashi add-on into Blender? (Without installing, the panel can still be shown for one session.)" On yes:

```bash
python <repo>/tools/install_addon.py
```

Add `--blender PATH` when Blender is not in its usual place. Without installing, every step below still works (the panel is shown by `scripts/kanzashi_panel.py`).

### 1. Detection and UV (no panel)

```bash
blender -b model.blend --python <repo>/scripts/kanzashi_run.py -- --out model_k1.blend --report k1.json
```

Read the last line `KANZASHI {...}` and `k1.json`.

| Field | What to make of it |
|---|---|
| `ok` | false: stop and tell the user `error` and `check` |
| `hairs[].wires` | number of strands; is it far from the number of locks you can see? |
| `hairs[].error` | that hair was left out; the others went on |
| `check.ok` | the UV check; when false, do not export or swap |
| `check.islands` | number of UV islands; much more than the strands means many tiny islands (see the limits) |

### 2. Pictures for checking

```bash
blender -b model_k1.blend --python <repo>/scripts/kanzashi_preview.py -- --out-dir k1_preview
```

Four pictures (front, back, left, right, in strand colours) and one of the UV. Look at them yourself too:

- Is one lock cut into two colours along its length?
- Are separate locks joined in one colour?
- Is the fused part at the crown divided lock by lock?

★ Show the pictures and ask "Is this split of the strands all right?" with the choices (a) go on, (b) I will repaint, (c) I want to bend some strands. Add what you noticed (for example "the front left lock is cut into two colours").

### 3. The user edits (paint, bend)

For (b) or (c) the user opens Blender. With the add-on installed, they just open `model_k1.blend`. Otherwise:

```bash
blender model_k1.blend --python <repo>/scripts/kanzashi_panel.py
```

Tell the user:

1. Open the "Kanzashi" tab of the sidebar (N key). The language is chosen at the top of the panel.
2. Press "Auto register" in step 1. **Do not press the detection of step 2 again** (the repainting would be lost).
3. Step 3 fixes colours, step 4 bends. Ctrl+Z undoes.
4. When done, **save under a new name** (for example `model_k2.blend`) and say so.

Wait until the user says the file is saved.

### 4. UV and check after the edit

```bash
blender -b model_k2.blend --python <repo>/scripts/kanzashi_run.py -- --out model_k3.blend --report k3.json
```

Check that `hairs[].kept_strands` is true. Make the pictures again (step 2).

★ Show them and ask "Are the strands and the shape final?" If not, go back to step 3.

### 5. Checking for strands inside the body

The agent checks whether strands pass into the body or the arms. This calculation is not in the add-on (in Blender the user can see it with their own eyes; the calculation is heavy, so it is for the agent's checking). Do it on a file that still has the wires (before the shape is applied).

First decide what to test against.

```bash
blender -b model_k3.blend --python <repo>/skills/kanzashi/scripts/hair_penetration.py -- list
```

Choose the **closed meshes** hair must not enter: body, arms, legs, tail. Do not choose the head (roots sit on the head on purpose; the first 5 cm of every strand at the root are left out anyway). Add clothes and ornaments only when the user cares about them. When unsure which mesh is the body, show the candidates and ask.

```bash
blender -b model_k3.blend --python <repo>/skills/kanzashi/scripts/hair_penetration.py -- check --against Body Arm --report pen.json --render-dir pen_img
```

`strands` lists the buried strands, deepest first.

| Field | Meaning |
|---|---|
| `wire` | number of the strand (wire); the same number as in the panel's list of colours |
| `kind` | `tip`: the tip is inside; `through`: the middle is inside and the strand comes out again |
| `depth_max_mm`, `buried_cm2` | depth at the deepest place, buried area |
| `along` | which part of the strand (0 root, 1 tip) |
| `warnings` | a partner that is not closed; results near its openings are unreliable |

In the pictures buried strands are red and the partners brown. `spot*.png` are close views of the deepest places. Look at them yourself and see that they agree with the numbers.

With no buried strand, say so and go on. Otherwise:

★ Show the list (wire numbers, depth, tip or through) and the pictures and ask "N strands go into the body. How shall they be fixed?"

| Choice | What to do |
|---|---|
| I fix them myself | as in step 3, the user moves the handles of step 4 in Blender; tell them the wire numbers. After they save, run `check` again |
| Fix them by the AI's plan | "The AI fixes" below |
| Leave them | nothing; write "N buried strands were left as they are" in the report |

**The AI fixes**: state the plan in words first: "I will move wires 6, 0 and 30 outward by 15-30 mm. Wire 40 is 26 mm deep, so I leave it." Strands deeper than `--max-depth-mm` (default 25) are not moved automatically: the move would be large and change the shape too much. The user bends or reroutes those.

```bash
blender -b model_k3.blend --python <repo>/skills/kanzashi/scripts/hair_penetration.py -- fix --against Body Arm --out model_k3b.blend --report fix.json --render-dir fix_img
```

- The wire is moved outward a little more than the depth, smoothly along the wire. The result is the same as if the user had moved the handles, and can be adjusted by hand afterwards.
- Read `wire_moved_mm`, `hair_moved_max_mm` (largest move of a hair vertex), `still_buried`, `new_buried` and `left_for_the_user` in the report.
- In the pictures moved strands are blue and strands still buried red. Use `all_*.png` to see that the shape of the hair has not been spoiled.

★ Show the pictures and numbers after the fix and ask "Is this fix all right?" On yes, go on with `model_k3b.blend`. Otherwise go back to `model_k3.blend` (it is untouched); the user fixes by hand, or run again limited to some strands with `--wire N`.

Only the pose of the file is tested. Other poses of the arms and hair against hair are not.

### 6. What the UV is for

★ Ask "How do you want to use the hair UV?"

| Choice | What to do |
|---|---|
| Make new textures | run with `--export hair.fbx`: the hair with the strand UV only. Decide with the user how the new textures come back. **Do not use Smart UV on the hair when texturing in Tripo** (see the note below) |
| Keep the look, switch to the new UV | run with `--swap`: the current textures are transferred to the new UV. `swap` in the report gives the number of triangles whose colour differs |
| Just add the UV | no flag: the UV map `LW_StrandUV` is added and rendering is unchanged |

```bash
blender -b model_k3.blend --python <repo>/scripts/kanzashi_run.py -- --out model_k4.blend --swap --report k4.json
```

**Note (always tell the user): do not use Smart UV on the hair when texturing in Tripo.** Smart UV makes a new UV, so the strand UV is lost. When the exported hair is handed over, say (with the export report) that the original UV must be kept. When the model comes back, check that the number and the layout of the UV islands are those of the export before using it; if they differ, Smart UV was applied: do not use it, and tell the user.

### 7. Applying the shape

The bending setup (wires and modifiers) can stay in the file, so the user can go on later.

★ Before an export (FBX, VRM and so on), or when the user says the hair will not be bent any more, ask "May I write the bent shape into the mesh and remove the wires? To bend again afterwards, the detection has to be redone." On yes, run with `--apply`. The strand colours and the UV stay.

### 8. Back to the production file

The result is a copy of the original file with the hair changed. Whether it replaces the original or is kept as another version follows the user's own rules. Do not overwrite on your own.

## What to report

- Which file was made from which.
- Number of strands, number of UV islands, the check (`check.ok`, the share of folded and squashed faces).
- What the hair was tested against, how many strands were buried, how they were fixed (user / AI / left), and the count afterwards.
- What the user confirmed, and their answers.
- What was not checked (for example moving the rig, the look in the target application).

## Known limits

- Tested with Blender 5.3 on Windows only.
- Painting is per face; nothing finer than a face can be painted.
- With flat sheet-like bangs, thin faces or shapes that do not unfold well, the detection gets coarse or the UV gets many more islands than strands.
- The wire of a branch does not follow the wire of its parent.
- Repaint before bending.
- A swap transfers only images read through a UV (not MatCap and the like).
- Untested on hair with shape keys.
- Blender does not respond during the slow steps; long hair takes tens of seconds to minutes. Give background runs a long time limit.
