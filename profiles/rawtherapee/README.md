# RawTherapee Profiles

This folder is for repository-controlled RawTherapee `.pp3` files used by the
local RAW61/PS16 break-even pipeline.

The renderer script defaults to:

```text
profiles/rawtherapee/neutral-render.pp3
```

Create that file from RawTherapee after choosing the exact neutral rendering
state you want to freeze for the study. The script intentionally refuses to
invent one, because the profile controls demosaicing, color management, white
balance, tone curves, and sharpening. Those choices must be explicit for the
RAW61-vs-PS16 comparison to mean anything.

