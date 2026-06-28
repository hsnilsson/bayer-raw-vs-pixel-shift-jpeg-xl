# Render Command Templates

The DNG commands use a template with:

- `{input}` for the DNG path
- `{output}` for the rendered TIFF path

Examples:

```powershell
--render-command 'darktable-cli "{input}" "{output}"'
```

If your renderer needs a sidecar/settings file, include it in the command:

```powershell
--render-command 'darktable-cli "{input}" "D:\profiles\neutral.xmp" "{output}"'
```

The goal is boring consistency: same renderer, same version, same settings, same output bit depth, same color space.
