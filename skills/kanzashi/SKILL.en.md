# Kanzashi: working with generated hair strand by strand

English version of [SKILL.md](SKILL.md). Agents working in English read this file.

Kanzashi is a Blender add-on. It splits a fused hair mesh into strands (one colour and one wire per strand), lets the split be fixed by painting colours, bends strands by their wires, and makes a UV map with one island per strand.
This skill says **when and in what order an agent uses it, and where it stops to ask the user**. The code is described in [README.en.md](../../README.en.md).

`<repo>` below is the place of this repository (two folders above this file).

## When to use it

- The hair is one mesh (or a few) fused together, and strands cannot be selected, bent or painted one by one.
- The user asks to fix the flow of the hair, or to move strands out of an arm or the body.
- A clean UV per strand is needed before the hair texture is made again.

Within the making of a character, do it **after the shape and place of the hair are settled and before the hair texture is redone**. The detection cuts the mesh along the strand borders (the vertex count grows), so do it before rigging and shape keys when you can. It also runs on rigged hair; then move the bones after the detection and check that the hair still follows the body.

Do not use it when the hair is already separate strand parts, when it is made of hair cards only, or when Blender is older than 5.3.

## Rules

- **Never change the original file.** The scripts do not save the opened file; the result goes to a new file. They stop when the output exists. Use a new output name every time.
- **Do not detect again on a file the user has repainted or bent.** `kanzashi_run.py` keeps the strands of a hair that is already detected. Use `--redetect` only when the user says "start over".
- **Install or update the add-on only with the user's permission.**
- Do not call it done on numbers alone. Whether the split is good is decided by the user looking at the pictures.
- Painting strand colours and bending wires are done by the user in Blender. The agent does not paint for them (which face belongs to which strand is a visual judgement).

## The steps, and where to ask the user

★ marks a stop to ask the user. Ask one thing at a time, with a picture, as a choice.

### 0. Prepare

1. Find Blender and check its version (5.3 or later).
2. Find the file and the names of the hair meshes. Meshes whose name or material names contain hair, bangs and the like are taken automatically. If an ornament might be taken, or the hair missed, name them with `--hair NAME`.
3. Check whether the add-on is installed.

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

### 5. What the UV is for

★ Ask "How do you want to use the hair UV?"

| Choice | What to do |
|---|---|
| Make new textures | run with `--export hair.fbx`: the hair with the strand UV only. Decide with the user how the new textures come back |
| Keep the look, switch to the new UV | run with `--swap`: the current textures are transferred to the new UV. `swap` in the report gives the number of triangles whose colour differs |
| Just add the UV | no flag: the UV map `LW_StrandUV` is added and rendering is unchanged |

```bash
blender -b model_k3.blend --python <repo>/scripts/kanzashi_run.py -- --out model_k4.blend --swap --report k4.json
```

### 6. Applying the shape

The bending setup (wires and modifiers) can stay in the file, so the user can go on later.

★ Before an export (FBX, VRM and so on), or when the user says the hair will not be bent any more, ask "May I write the bent shape into the mesh and remove the wires? To bend again afterwards, the detection has to be redone." On yes, run with `--apply`. The strand colours and the UV stay.

### 7. Back to the production file

The result is a copy of the original file with the hair changed. Whether it replaces the original or is kept as another version follows the user's own rules. Do not overwrite on your own.

## What to report

- Which file was made from which.
- Number of strands, number of UV islands, the check (`check.ok`, the share of folded and squashed faces).
- What the user confirmed, and their answers.
- What was not checked (for example moving the rig, the look in the target application).

## Known limits

- A prototype, tested with Blender 5.3 on Windows only.
- Painting is per face; nothing finer than a face can be painted.
- With flat sheet-like bangs, thin faces or shapes that do not unfold well, the detection gets coarse or the UV gets many more islands than strands.
- The wire of a branch does not follow the wire of its parent.
- Repaint before bending.
- A swap transfers only images read through a UV (not MatCap and the like).
- Untested on hair with shape keys.
- Blender does not respond during the slow steps; long hair takes tens of seconds to minutes. Give background runs a long time limit.
