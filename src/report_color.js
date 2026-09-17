/* ICC matrix/TRC display contract, shared by the report and numerical oracle tests. */
const ReportColor = (() => {
  const clip = x => Math.max(0, Math.min(1, x));
  const decodeSrgb = x => x <= .04045 ? x / 12.92 : Math.pow((x + .055) / 1.055, 2.4);
  const encodeSrgb = x => x <= .0031308 ? 12.92 * x : 1.055 * Math.pow(Math.max(x, 0), 1 / 2.4) - .055;
  function decode(x, curve) {
    if (curve.kind === "srgb") return decodeSrgb(x);
    if (curve.kind === "gamma") return Math.pow(Math.max(x, 0), curve.gamma);
    if (curve.kind === "table") {
      const p = clip(x) * (curve.values.length - 1), i = Math.floor(p);
      return curve.values[i] + (curve.values[Math.min(i + 1, curve.values.length - 1)] - curve.values[i]) * (p - i);
    }
    const [g, a, b, c, d, e, f] = curve.parameters;
    const kind = curve.function;
    if (kind === 0) return Math.pow(Math.max(x, 0), g);
    const high = Math.pow(Math.max(a * x + b, 0), g);
    if (kind === 1) return x >= -b / a ? high : 0;
    if (kind === 2) return x >= -b / a ? high + c : c;
    if (kind === 3) return x >= d ? high : c * x;
    if (kind === 4) return x >= d ? high + e : c * x + f;
    throw new Error("Unsupported ICC curve");
  }
  function transformed(linear, mode, recipe) {
    if (mode === "identity") return linear;
    if (mode === "shadow_recovery_luma_p12" || mode === "highlight_separation_luma_p88_p998") {
      const y = linear.reduce((sum, value, i) => sum + value * recipe.luma_weights[i], 0);
      const v = clip(mode === "shadow_recovery_luma_p12" ? y / recipe.shadow_white
        : (y - recipe.highlight_black) / (recipe.highlight_white - recipe.highlight_black));
      return [v, v, v];
    }
    if (!["negative_density_hard_print", "negative_density_hard_shadow_recovery"].includes(mode)) throw new Error("Undeclared transform");
    const balance = [1.07, 1, .94];
    const low = 1 / (1 + Math.exp(4.5)), high = 1 / (1 + Math.exp(-4.5));
    return linear.map((value, i) => {
      const t = Math.max(1e-5, Math.min(1, (value - recipe.density_black[i]) / Math.max(1e-6, recipe.density_base[i] - recipe.density_black[i])));
      let p = clip((-Math.log(t) - recipe.density_low[i]) / Math.max(1e-6, recipe.density_high[i] - recipe.density_low[i]));
      p = clip((p - .035) / .90);
      if (mode.endsWith("shadow_recovery")) p = Math.pow(p, .68);
      p = clip(p * balance[i]);
      return (1 / (1 + Math.exp(-9 * (p - .5))) - low) / (high - low);
    });
  }
  function display(encoded, recipe, mode = "identity", exposure = 0, inputProfile = recipe.profile) {
    if (recipe.schema !== 3 || !recipe.profile) throw new Error("Viewer requires verified ICC recipe schema 3");
    const decoded = encoded.map((v, i) => decode(v, inputProfile.curves[i]));
    const linear = inputProfile.linear_to_reference
      ? inputProfile.linear_to_reference.map(row => row.reduce((sum, v, i) => sum + v * decoded[i], 0) * Math.pow(2, exposure))
      : decoded.map(v => v * Math.pow(2, exposure));
    const working = transformed(linear, mode, recipe);
    return recipe.profile.linear_to_srgb.map(row => encodeSrgb(row.reduce((sum, v, i) => sum + v * working[i], 0)));
  }
  const curveCache = new Map();
  function compileU16(recipe, mode = "identity", exposure = 0, inputProfile = recipe.profile) {
    if (recipe.schema !== 3 || !recipe.profile) throw new Error("Viewer requires verified ICC recipe schema 3");
    const curves = inputProfile.curves.map(curve => {
      const key = JSON.stringify(curve);
      if (!curveCache.has(key)) {
        const table = new Float64Array(65536);
        for (let i = 0; i < table.length; i++) table[i] = decode(i / 65535, curve);
        curveCache.set(key, table);
        if (curveCache.size > 8) curveCache.delete(curveCache.keys().next().value);
      }
      return curveCache.get(key);
    });
    const m = inputProfile.linear_to_reference || [[1,0,0],[0,1,0],[0,0,1]];
    const out = recipe.profile.linear_to_srgb, gain = Math.pow(2, exposure);
    const gray = mode === "shadow_recovery_luma_p12" || mode === "highlight_separation_luma_p88_p998";
    const density = mode === "negative_density_hard_print" || mode === "negative_density_hard_shadow_recovery";
    if (mode !== "identity" && !gray && !density) throw new Error("Undeclared transform");
    const lift = mode === "negative_density_hard_shadow_recovery", balance = [1.07,1,.94];
    const low = 1 / (1 + Math.exp(4.5)), span = 1 / (1 + Math.exp(-4.5)) - low;
    function densityValue(value, i) {
      const t = Math.max(1e-5, Math.min(1, (value - recipe.density_black[i]) / Math.max(1e-6, recipe.density_base[i] - recipe.density_black[i])));
      let p = clip((-Math.log(t) - recipe.density_low[i]) / Math.max(1e-6, recipe.density_high[i] - recipe.density_low[i]));
      p = clip((p - .035) / .90);
      if (lift) p = Math.pow(p, .68);
      p = clip(p * balance[i]);
      return (1 / (1 + Math.exp(-9 * (p - .5))) - low) / span;
    }
    // Exact transfer-curve values for every possible input code. Matrix and
    // display operations remain floating point, with no LUT output clipping.
    return (r, g, b, result) => {
      r = curves[0][r]; g = curves[1][g]; b = curves[2][b];
      let a = (m[0][0]*r + m[0][1]*g + m[0][2]*b) * gain;
      let c = (m[1][0]*r + m[1][1]*g + m[1][2]*b) * gain;
      let d = (m[2][0]*r + m[2][1]*g + m[2][2]*b) * gain;
      if (gray) {
        const y = a*recipe.luma_weights[0] + c*recipe.luma_weights[1] + d*recipe.luma_weights[2];
        a = c = d = clip(mode === "shadow_recovery_luma_p12" ? y / recipe.shadow_white : (y-recipe.highlight_black)/(recipe.highlight_white-recipe.highlight_black));
      } else if (density) {
        a = densityValue(a,0); c = densityValue(c,1); d = densityValue(d,2);
      }
      result[0] = encodeSrgb(out[0][0]*a + out[0][1]*c + out[0][2]*d);
      result[1] = encodeSrgb(out[1][0]*a + out[1][1]*c + out[1][2]*d);
      result[2] = encodeSrgb(out[2][0]*a + out[2][1]*c + out[2][2]*d);
    };
  }
  return { decode, decodeSrgb, encodeSrgb, transformed, display, compileU16 };
})();
if (typeof module !== "undefined") module.exports = ReportColor;
