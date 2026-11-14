# DigiFlot Edge — Color Palette

**Status:** Applied in the `main` branch on 2026-11-14. This is the current palette reference.
**Canonical CSS:** [`src/ui/css/common.css`](src/ui/css/common.css)  
**Historical A → B audit:** [`HIF_COLOR_AUDIT_AND_MIGRATION.md`](src/docs/HIF_COLOR_AUDIT_AND_MIGRATION.md)

The palette preserves the existing dark UI and brings its blue and orange accents closer to HIF/Helmholtz identity. The historic Helmholtz design guide documents `#00589C`, `#003E6E`, `#00A2E0` and `#E6AF11`; HIF orange `#F47721` is an approximate logo-inspired value, not a verified official 2026 HIF color specification.

## Visual overview

![DigiFlot old and new colors side-by-side](src/docs/assets/HIF_COLOR_COMPARISON.svg)

| Context | Cor A · anterior | → | Cor B · aplicada | CSS / uso |
|---|---|:---:|---|---|
| Azul principal / CTA | ![#2F6FED](https://img.shields.io/badge/%20-%20-2F6FED?style=flat-square) `#2F6FED` | → | ![#176FA6](https://img.shields.io/badge/%20-%20-176FA6?style=flat-square) `#176FA6` | `--action-background (dark)` |
| Hover de CTA | ![#255ED0](https://img.shields.io/badge/%20-%20-255ED0?style=flat-square) `#255ED0` | → | ![#105C90](https://img.shields.io/badge/%20-%20-105C90?style=flat-square) `#105C90` | `--action-hover (dark)` |
| Texto de link e foco | ![#2F6FED](https://img.shields.io/badge/%20-%20-2F6FED?style=flat-square) `#2F6FED` | → | ![#69B9E8](https://img.shields.io/badge/%20-%20-69B9E8?style=flat-square) `#69B9E8` | `--interactive-text (dark)` |
| Preview / câmera | ![#7254D8](https://img.shields.io/badge/%20-%20-7254D8?style=flat-square) `#7254D8` | → | ![#00A2E0](https://img.shields.io/badge/%20-%20-00A2E0?style=flat-square) `#00A2E0` | `--preview` |
| Passed / sucesso | ![#18845B](https://img.shields.io/badge/%20-%20-18845B?style=flat-square) `#18845B` | → | ![#23865D](https://img.shields.io/badge/%20-%20-23865D?style=flat-square) `#23865D` | `--success` |
| Alerta / skipped | ![#C47A12](https://img.shields.io/badge/%20-%20-C47A12?style=flat-square) `#C47A12` | → | ![#D08A28](https://img.shields.io/badge/%20-%20-D08A28?style=flat-square) `#D08A28` | `--warning` |
| Erro / abort | ![#C74242](https://img.shields.io/badge/%20-%20-C74242?style=flat-square) `#C74242` | → | ![#C94B3E](https://img.shields.io/badge/%20-%20-C94B3E?style=flat-square) `#C94B3E` | `--danger` |
| Realce laranja | ![#F59E0B](https://img.shields.io/badge/%20-%20-F59E0B?style=flat-square) `#F59E0B` | → | ![#F47721](https://img.shields.io/badge/%20-%20-F47721?style=flat-square) `#F47721` | `--hif-orange` |
| Interface superior | ![#0EA5E9](https://img.shields.io/badge/%20-%20-0EA5E9?style=flat-square) `#0EA5E9` | → | ![#29AEE4](https://img.shields.io/badge/%20-%20-29AEE4?style=flat-square) `#29AEE4` | `--plot-froth-upper` |
| Referência / linha azul | ![#38BDF8](https://img.shields.io/badge/%20-%20-38BDF8?style=flat-square) `#38BDF8` | → | ![#55BAE7](https://img.shields.io/badge/%20-%20-55BAE7?style=flat-square) `#55BAE7` | `--plot-froth` |
| Interface inferior | ![#FBBF24](https://img.shields.io/badge/%20-%20-FBBF24?style=flat-square) `#FBBF24` | → | ![#E6AF11](https://img.shields.io/badge/%20-%20-E6AF11?style=flat-square) `#E6AF11` | `--plot-pulp-secondary` |
| Seleção de ROI | ![#22D3EE](https://img.shields.io/badge/%20-%20-22D3EE?style=flat-square) `#22D3EE` | → | ![#28BEE8](https://img.shields.io/badge/%20-%20-28BEE8?style=flat-square) `#28BEE8` | `--roi-cyan` |
| ROI em edição | ![#FACC15](https://img.shields.io/badge/%20-%20-FACC15?style=flat-square) `#FACC15` | → | ![#E6AF11](https://img.shields.io/badge/%20-%20-E6AF11?style=flat-square) `#E6AF11` | `--roi-yellow` |
| Plano de câmera | ![#17212B](https://img.shields.io/badge/%20-%20-17212B?style=flat-square) `#17212B` | → | ![#172637](https://img.shields.io/badge/%20-%20-172637?style=flat-square) `#172637` | `background de diagnóstico` |
| Área de imagem | ![#101827](https://img.shields.io/badge/%20-%20-101827?style=flat-square) `#101827` | → | ![#122131](https://img.shields.io/badge/%20-%20-122131?style=flat-square) `#122131` | `background de mídia` |
| Toast | ![#17202A](https://img.shields.io/badge/%20-%20-17202A?style=flat-square) `#17202A` | → | ![#162B3A](https://img.shields.io/badge/%20-%20-162B3A?style=flat-square) `#162B3A` | `fundo de feedback` |
| Texto secundário | ![#435162](https://img.shields.io/badge/%20-%20-435162?style=flat-square) `#435162` | → | ![#44596B](https://img.shields.io/badge/%20-%20-44596B?style=flat-square) `#44596B` | `em superfícies claras` |
| Texto discreto | ![#728294](https://img.shields.io/badge/%20-%20-728294?style=flat-square) `#728294` | → | ![#748A9D](https://img.shields.io/badge/%20-%20-748A9D?style=flat-square) `#748A9D` | `em superfícies claras` |
| Bordas neutras | ![#AEB9C4](https://img.shields.io/badge/%20-%20-AEB9C4?style=flat-square) `#AEB9C4` | → | ![#A7BDCC](https://img.shields.io/badge/%20-%20-A7BDCC?style=flat-square) `#A7BDCC` | `em superfícies claras` |
| Fundo do vídeo | ![#000000](https://img.shields.io/badge/%20-%20-000000?style=flat-square) `#000000` | → | ![#000000](https://img.shields.io/badge/%20-%20-000000?style=flat-square) `#000000` | `preservado` |

## Current palette and semantic tokens

| Context | Current swatch / HEX | Token | Primary use |
|---|---|---|---|
| HIF blue | ![#00589C](https://img.shields.io/badge/%20-%20-00589C?style=flat-square) `#00589C` | `--hif-blue` | Referência histórica Helmholtz; botões no tema claro |
| HIF dark blue | ![#003E6E](https://img.shields.io/badge/%20-%20-003E6E?style=flat-square) `#003E6E` | `--hif-dark-blue` | Hover no tema claro |
| HIF light blue | ![#00A2E0](https://img.shields.io/badge/%20-%20-00A2E0?style=flat-square) `#00A2E0` | `--hif-light-blue / --preview` | Preview e identificação de câmera |
| HIF orange | ![#F47721](https://img.shields.io/badge/%20-%20-F47721?style=flat-square) `#F47721` | `--hif-orange / --plot-pulp` | Realces e curva inferior |
| Energy yellow | ![#E6AF11](https://img.shields.io/badge/%20-%20-E6AF11?style=flat-square) `#E6AF11` | `--hif-energy-yellow / --plot-pulp-secondary` | Limites e marcações físicas |
| Action blue (dark) | ![#176FA6](https://img.shields.io/badge/%20-%20-176FA6?style=flat-square) `#176FA6` | `--action-background` | Botões preenchidos |
| Action hover (dark) | ![#105C90](https://img.shields.io/badge/%20-%20-105C90?style=flat-square) `#105C90` | `--action-hover` | Hover de botão preenchido |
| Interactive text (dark) | ![#69B9E8](https://img.shields.io/badge/%20-%20-69B9E8?style=flat-square) `#69B9E8` | `--interactive-text` | Links, foco, títulos selecionados |
| Success background | ![#23865D](https://img.shields.io/badge/%20-%20-23865D?style=flat-square) `#23865D` | `--success` | Indicadores e cores sólidas |
| Success text (dark) | ![#5FC796](https://img.shields.io/badge/%20-%20-5FC796?style=flat-square) `#5FC796` | `--success-text` | Textos pequenos de estado |
| Warning background | ![#D08A28](https://img.shields.io/badge/%20-%20-D08A28?style=flat-square) `#D08A28` | `--warning` | Alertas e avisos |
| Warning text (dark) | ![#F1BE69](https://img.shields.io/badge/%20-%20-F1BE69?style=flat-square) `#F1BE69` | `--warning-text` | Textos pequenos de estado |
| Danger background | ![#C94B3E](https://img.shields.io/badge/%20-%20-C94B3E?style=flat-square) `#C94B3E` | `--danger` | Abort e erros |
| Danger text (dark) | ![#F28A7C](https://img.shields.io/badge/%20-%20-F28A7C?style=flat-square) `#F28A7C` | `--danger-text` | Textos pequenos de erro |
| Froth selected line | ![#55BAE7](https://img.shields.io/badge/%20-%20-55BAE7?style=flat-square) `#55BAE7` | `--plot-froth` | Overlay sobre imagem |
| Froth upper curve | ![#29AEE4](https://img.shields.io/badge/%20-%20-29AEE4?style=flat-square) `#29AEE4` | `--plot-froth-upper` | Linha do limite superior |
| Froth lower curve | ![#F47721](https://img.shields.io/badge/%20-%20-F47721?style=flat-square) `#F47721` | `--plot-pulp` | Linha do limite inferior |

### Adaptive colors

The global stylesheet supports `color-scheme: light dark`. Solid button color and small text color are different roles:

| Token | Light | Dark |
|---|---|---|
| `--action-background` | ![#00589C](https://img.shields.io/badge/%20-%20-00589C?style=flat-square) `#00589C` | ![#176FA6](https://img.shields.io/badge/%20-%20-176FA6?style=flat-square) `#176FA6` |
| `--action-hover` | ![#003E6E](https://img.shields.io/badge/%20-%20-003E6E?style=flat-square) `#003E6E` | ![#105C90](https://img.shields.io/badge/%20-%20-105C90?style=flat-square) `#105C90` |
| `--interactive-text` | ![#00589C](https://img.shields.io/badge/%20-%20-00589C?style=flat-square) `#00589C` | ![#69B9E8](https://img.shields.io/badge/%20-%20-69B9E8?style=flat-square) `#69B9E8` |
| `--success-text` | ![#196544](https://img.shields.io/badge/%20-%20-196544?style=flat-square) `#196544` | ![#5FC796](https://img.shields.io/badge/%20-%20-5FC796?style=flat-square) `#5FC796` |
| `--warning-text` | ![#986012](https://img.shields.io/badge/%20-%20-986012?style=flat-square) `#986012` | ![#F1BE69](https://img.shields.io/badge/%20-%20-F1BE69?style=flat-square) `#F1BE69` |
| `--danger-text` | ![#AB332B](https://img.shields.io/badge/%20-%20-AB332B?style=flat-square) `#AB332B` | ![#F28A7C](https://img.shields.io/badge/%20-%20-F28A7C?style=flat-square) `#F28A7C` |
| `--preview-text` | ![#006B98](https://img.shields.io/badge/%20-%20-006B98?style=flat-square) `#006B98` | ![#66CFEF](https://img.shields.io/badge/%20-%20-66CFEF?style=flat-square) `#66CFEF` |

Neutrals remain adaptive via `Canvas`, `CanvasText`, and `color-mix()`. Avoid replacing the base background or body copy with saturated brand colors. `--accent`, `--accent-hover`, `--success`, `--warning`, `--danger`, and `--preview` are backward-compatible aliases for existing selectors.

Example:
```css
.primary-action { background: var(--action-background); color: #fff; }
.primary-action:hover { background: var(--action-hover); }
.link:focus-visible { outline: 2px solid var(--interactive-text); }
.status-passed { color: var(--success-text); background: var(--success-soft); }
.froth-upper { color: var(--plot-froth-upper); }
.froth-lower { color: var(--plot-pulp); }
```

### Semantic rules

1. **Do not use button blue as dark-mode body text.** Use `--interactive-text`, not `--action-background`, for small text and links.
2. **Do not conflate brand colors with process status.** Passed stays green, warning/skipped amber, failures and Abort red.
3. **Keep measurements distinct.** Froth upper boundary is blue/cyan, lower boundary orange/yellow; reference overlays keep their selection emphasis.
4. **Keep calibrated imagery untouched.** Color tokens change borders, grids and overlays, never captured camera frames or the HIF logo asset.
5. **Use semantic tokens in new CSS and Canvas code.** Do not repeat `:root` palette declarations in individual page stylesheets.
6. **Preserve existing neutral surface hierarchy.** `--bg`, `--surface`, `--text`, `--border` and the shadow tokens remain platform-aware.
7. **Check light and dark appearance.** Nominal white on dark action blue `#176FA6` is about 5.44:1, and white on brand blue `#00589C` about 7.30:1; other contexts still require practical visual checks.

## Implementation locations

The complete palette is centrally defined in `src/ui/css/common.css`. The mapped CSS pages are:
`cells.css`, `config_camera.css`, `experiments.css`, `performance.css`, `results.css`, `run.css`, `sensors.css`, and `settings.css`.

The `run.js`, `sensors.js`, and `results.js` Canvas overlays and plots were updated to use matching palette values or computed CSS variables. Jinja templates use versioned style URLs to invalidate browser caches. Automated checks are implemented in `tests/test_color_palette.js`; hardware UI checks at actual Raspberry Pi resolutions remain recommended.

## Complete historical HEX mapping

The following table reproduces all **60 distinct original HEX values** from the audit, including colors intentionally retained. The mapping is contextual: the active source of truth is the semantic token, not an indiscriminate text substitution.

### All original HEX colors, A → B

This is a **proposed mapping**, not an instruction to replace every occurrence blindly: one source color may need different semantic tokens depending on its property and background. The table below includes a representative context for **all 60 original HEX values**. For 8-digit HEX colors, the small swatch displays their RGB hue, and the text retains the exact alpha value.

### Interactive/HIF blues

| Context | Color A · current | → | Color B · proposed |
|---|---|:---:|---|
| Primary accent / controls (12 uses) | ![#2F6FED](https://img.shields.io/badge/%20-%20-2F6FED?style=flat-square) `#2F6FED` | → | ![#176FA6](https://img.shields.io/badge/%20-%20-176FA6?style=flat-square) `#176FA6` |
| Interactive hover (6 uses) | ![#255ED0](https://img.shields.io/badge/%20-%20-255ED0?style=flat-square) `#255ED0` | → | ![#105C90](https://img.shields.io/badge/%20-%20-105C90?style=flat-square) `#105C90` |
| Experiment button hover (1 use) | ![#285FCD](https://img.shields.io/badge/%20-%20-285FCD?style=flat-square) `#285FCD` | → | ![#0E628E](https://img.shields.io/badge/%20-%20-0E628E?style=flat-square) `#0E628E` |
| Active-state border (3 uses) | ![#CBDAFD](https://img.shields.io/badge/%20-%20-CBDAFD?style=flat-square) `#CBDAFD` | → | ![#BFDDED](https://img.shields.io/badge/%20-%20-BFDDED?style=flat-square) `#BFDDED` |
| Information outline (2 uses) | ![#D8E3FB](https://img.shields.io/badge/%20-%20-D8E3FB?style=flat-square) `#D8E3FB` | → | ![#C6E4F2](https://img.shields.io/badge/%20-%20-C6E4F2?style=flat-square) `#C6E4F2` |
| Experiment selection (1 use) | ![#D9E5FF](https://img.shields.io/badge/%20-%20-D9E5FF?style=flat-square) `#D9E5FF` | → | ![#CBE7F2](https://img.shields.io/badge/%20-%20-CBE7F2?style=flat-square) `#CBE7F2` |
| Selected reference / Froth (4 uses) | ![#38BDF8](https://img.shields.io/badge/%20-%20-38BDF8?style=flat-square) `#38BDF8` | → | ![#55BAE7](https://img.shields.io/badge/%20-%20-55BAE7?style=flat-square) `#55BAE7` |
| Upper Froth curve (3 uses) | ![#0EA5E9](https://img.shields.io/badge/%20-%20-0EA5E9?style=flat-square) `#0EA5E9` | → | ![#29AEE4](https://img.shields.io/badge/%20-%20-29AEE4?style=flat-square) `#29AEE4` |
| ROI cyan outline (1 use) | ![#22D3EE](https://img.shields.io/badge/%20-%20-22D3EE?style=flat-square) `#22D3EE` | → | ![#28BEE8](https://img.shields.io/badge/%20-%20-28BEE8?style=flat-square) `#28BEE8` |
| ROI cyan fill (alpha) (1 use) | ![#22D3EE20](https://img.shields.io/badge/%20-%20-22D3EE?style=flat-square) `#22D3EE20` | → | ![#28BEE820](https://img.shields.io/badge/%20-%20-28BEE8?style=flat-square) `#28BEE820` |
| Preview outline (1 use) | ![#DDD6FF](https://img.shields.io/badge/%20-%20-DDD6FF?style=flat-square) `#DDD6FF` | → | ![#B4E1F4](https://img.shields.io/badge/%20-%20-B4E1F4?style=flat-square) `#B4E1F4` |
| Preview status (10 uses) | ![#7254D8](https://img.shields.io/badge/%20-%20-7254D8?style=flat-square) `#7254D8` | → | ![#00A2E0](https://img.shields.io/badge/%20-%20-00A2E0?style=flat-square) `#00A2E0` |

### Warning/energy/HIF orange

| Context | Color A · current | → | Color B · proposed |
|---|---|:---:|---|
| ROI yellow outline (1 use) | ![#FACC15](https://img.shields.io/badge/%20-%20-FACC15?style=flat-square) `#FACC15` | → | ![#E6AF11](https://img.shields.io/badge/%20-%20-E6AF11?style=flat-square) `#E6AF11` |
| ROI yellow fill (alpha) (1 use) | ![#FACC1522](https://img.shields.io/badge/%20-%20-FACC15?style=flat-square) `#FACC1522` | → | ![#E6AF1122](https://img.shields.io/badge/%20-%20-E6AF11?style=flat-square) `#E6AF1122` |
| Reference label / pulp (3 uses) | ![#F59E0B](https://img.shields.io/badge/%20-%20-F59E0B?style=flat-square) `#F59E0B` | → | ![#F47721](https://img.shields.io/badge/%20-%20-F47721?style=flat-square) `#F47721` |
| Lower Froth boundary (2 uses) | ![#FBBF24](https://img.shields.io/badge/%20-%20-FBBF24?style=flat-square) `#FBBF24` | → | ![#E6AF11](https://img.shields.io/badge/%20-%20-E6AF11?style=flat-square) `#E6AF11` |
| Warning outline (2 uses) | ![#EFCE93](https://img.shields.io/badge/%20-%20-EFCE93?style=flat-square) `#EFCE93` | → | ![#E9CBA0](https://img.shields.io/badge/%20-%20-E9CBA0?style=flat-square) `#E9CBA0` |
| Warning token (13 uses) | ![#C47A12](https://img.shields.io/badge/%20-%20-C47A12?style=flat-square) `#C47A12` | → | ![#D08A28](https://img.shields.io/badge/%20-%20-D08A28?style=flat-square) `#D08A28` |
| Warning surface (1 use) | ![#F0D8AD](https://img.shields.io/badge/%20-%20-F0D8AD?style=flat-square) `#F0D8AD` | → | ![#E9CEA8](https://img.shields.io/badge/%20-%20-E9CEA8?style=flat-square) `#E9CEA8` |
| Warning text (retained) (1 use) | ![#704300](https://img.shields.io/badge/%20-%20-704300?style=flat-square) `#704300` | → | ![#704300](https://img.shields.io/badge/%20-%20-704300?style=flat-square) `#704300` · keep |
| Skipped-calibration border (1 use) | ![#EAD7AE](https://img.shields.io/badge/%20-%20-EAD7AE?style=flat-square) `#EAD7AE` | → | ![#E4CCA6](https://img.shields.io/badge/%20-%20-E4CCA6?style=flat-square) `#E4CCA6` |

### Success and danger

| Context | Color A · current | → | Color B · proposed |
|---|---|:---:|---|
| Success token (13 uses) | ![#18845B](https://img.shields.io/badge/%20-%20-18845B?style=flat-square) `#18845B` | → | ![#23865D](https://img.shields.io/badge/%20-%20-23865D?style=flat-square) `#23865D` |
| Success outline (8 uses) | ![#CFE5DB](https://img.shields.io/badge/%20-%20-CFE5DB?style=flat-square) `#CFE5DB` | → | ![#C7E6D7](https://img.shields.io/badge/%20-%20-C7E6D7?style=flat-square) `#C7E6D7` |
| Danger token (13 uses) | ![#C74242](https://img.shields.io/badge/%20-%20-C74242?style=flat-square) `#C74242` | → | ![#C94B3E](https://img.shields.io/badge/%20-%20-C94B3E?style=flat-square) `#C94B3E` |
| Danger outline (8 uses) | ![#F3CCCC](https://img.shields.io/badge/%20-%20-F3CCCC?style=flat-square) `#F3CCCC` | → | ![#EEC7C2](https://img.shields.io/badge/%20-%20-EEC7C2?style=flat-square) `#EEC7C2` |
| Danger text (1 use) | ![#A51F1F](https://img.shields.io/badge/%20-%20-A51F1F?style=flat-square) `#A51F1F` | → | ![#B73A30](https://img.shields.io/badge/%20-%20-B73A30?style=flat-square) `#B73A30` |
| Destructive action (3 uses) | ![#C43D3D](https://img.shields.io/badge/%20-%20-C43D3D?style=flat-square) `#C43D3D` | → | ![#BC493C](https://img.shields.io/badge/%20-%20-BC493C?style=flat-square) `#BC493C` |

### Surfaces/text/borders/video

| Context | Color A · current | → | Color B · proposed |
|---|---|:---:|---|
| Secondary label (3 uses) | ![#435162](https://img.shields.io/badge/%20-%20-435162?style=flat-square) `#435162` | → | ![#44596B](https://img.shields.io/badge/%20-%20-44596B?style=flat-square) `#44596B` |
| Diagnostic background (3 uses) | ![#17212B](https://img.shields.io/badge/%20-%20-17212B?style=flat-square) `#17212B` | → | ![#172637](https://img.shields.io/badge/%20-%20-172637?style=flat-square) `#172637` |
| Muted text (3 uses) | ![#728294](https://img.shields.io/badge/%20-%20-728294?style=flat-square) `#728294` | → | ![#748A9D](https://img.shields.io/badge/%20-%20-748A9D?style=flat-square) `#748A9D` |
| White text (retained) (7 uses) | ![#FFF](https://img.shields.io/badge/%20-%20-FFF?style=flat-square) `#FFF` | → | ![#FFF](https://img.shields.io/badge/%20-%20-FFF?style=flat-square) `#FFF` · keep |
| White overlay (retained) (6 uses) | ![#FFFFFF](https://img.shields.io/badge/%20-%20-FFFFFF?style=flat-square) `#FFFFFF` | → | ![#FFFFFF](https://img.shields.io/badge/%20-%20-FFFFFF?style=flat-square) `#FFFFFF` · keep |
| Video black (retained) (3 uses) | ![#000](https://img.shields.io/badge/%20-%20-000?style=flat-square) `#000` | → | ![#000](https://img.shields.io/badge/%20-%20-000?style=flat-square) `#000` · keep |
| Black shadow alpha (retained) (1 use) | ![#0003](https://img.shields.io/badge/%20-%20-0003?style=flat-square) `#0003` | → | ![#0003](https://img.shields.io/badge/%20-%20-0003?style=flat-square) `#0003` · keep |
| Neutral outline (1 use) | ![#CBD4DD](https://img.shields.io/badge/%20-%20-CBD4DD?style=flat-square) `#CBD4DD` | → | ![#C3D3DF](https://img.shields.io/badge/%20-%20-C3D3DF?style=flat-square) `#C3D3DF` |
| Cell image border (1 use) | ![#243047](https://img.shields.io/badge/%20-%20-243047?style=flat-square) `#243047` | → | ![#22394D](https://img.shields.io/badge/%20-%20-22394D?style=flat-square) `#22394D` |
| Cell image background (1 use) | ![#101827](https://img.shields.io/badge/%20-%20-101827?style=flat-square) `#101827` | → | ![#122131](https://img.shields.io/badge/%20-%20-122131?style=flat-square) `#122131` |
| Cell image hint (1 use) | ![#9CAEC8](https://img.shields.io/badge/%20-%20-9CAEC8?style=flat-square) `#9CAEC8` | → | ![#9DB7CF](https://img.shields.io/badge/%20-%20-9DB7CF?style=flat-square) `#9DB7CF` |
| ROI shadow alpha (1 use) | ![#0F172A80](https://img.shields.io/badge/%20-%20-0F172A?style=flat-square) `#0F172A80` | → | ![#0F2B4080](https://img.shields.io/badge/%20-%20-0F2B40?style=flat-square) `#0F2B4080` |
| Subtle outline (2 uses) | ![#AEB9C4](https://img.shields.io/badge/%20-%20-AEB9C4?style=flat-square) `#AEB9C4` | → | ![#A7BDCC](https://img.shields.io/badge/%20-%20-A7BDCC?style=flat-square) `#A7BDCC` |
| Switch surface (1 use) | ![#D7DEE5](https://img.shields.io/badge/%20-%20-D7DEE5?style=flat-square) `#D7DEE5` | → | ![#D5E3EC](https://img.shields.io/badge/%20-%20-D5E3EC?style=flat-square) `#D5E3EC` |
| Switch border (1 use) | ![#BDC8D2](https://img.shields.io/badge/%20-%20-BDC8D2?style=flat-square) `#BDC8D2` | → | ![#B7CBD6](https://img.shields.io/badge/%20-%20-B7CBD6?style=flat-square) `#B7CBD6` |
| Input hover border (1 use) | ![#AEBAC6](https://img.shields.io/badge/%20-%20-AEBAC6?style=flat-square) `#AEBAC6` | → | ![#B3C5D0](https://img.shields.io/badge/%20-%20-B3C5D0?style=flat-square) `#B3C5D0` |
| Secondary action text (1 use) | ![#3D4C5D](https://img.shields.io/badge/%20-%20-3D4C5D?style=flat-square) `#3D4C5D` | → | ![#40586B](https://img.shields.io/badge/%20-%20-40586B?style=flat-square) `#40586B` |
| Camera placeholder text (1 use) | ![#D1DAE3](https://img.shields.io/badge/%20-%20-D1DAE3?style=flat-square) `#D1DAE3` | → | ![#CCDCE7](https://img.shields.io/badge/%20-%20-CCDCE7?style=flat-square) `#CCDCE7` |
| Muted camera hint (1 use) | ![#8FA0B0](https://img.shields.io/badge/%20-%20-8FA0B0?style=flat-square) `#8FA0B0` | → | ![#8FAABA](https://img.shields.io/badge/%20-%20-8FAABA?style=flat-square) `#8FAABA` |
| Information border (1 use) | ![#A9B8C8](https://img.shields.io/badge/%20-%20-A9B8C8?style=flat-square) `#A9B8C8` | → | ![#AAC3D1](https://img.shields.io/badge/%20-%20-AAC3D1?style=flat-square) `#AAC3D1` |
| Information background (1 use) | ![#F0F4F7](https://img.shields.io/badge/%20-%20-F0F4F7?style=flat-square) `#F0F4F7` | → | ![#F0F6FA](https://img.shields.io/badge/%20-%20-F0F6FA?style=flat-square) `#F0F6FA` |
| Information text (1 use) | ![#607080](https://img.shields.io/badge/%20-%20-607080?style=flat-square) `#607080` | → | ![#607C8E](https://img.shields.io/badge/%20-%20-607C8E?style=flat-square) `#607C8E` |
| Light background (1 use) | ![#F7FAFF](https://img.shields.io/badge/%20-%20-F7FAFF?style=flat-square) `#F7FAFF` | → | ![#F5FAFD](https://img.shields.io/badge/%20-%20-F5FAFD?style=flat-square) `#F5FAFD` |
| Calibration description (1 use) | ![#657282](https://img.shields.io/badge/%20-%20-657282?style=flat-square) `#657282` | → | ![#607B8D](https://img.shields.io/badge/%20-%20-607B8D?style=flat-square) `#607B8D` |
| Preview frame (1 use) | ![#263342](https://img.shields.io/badge/%20-%20-263342?style=flat-square) `#263342` | → | ![#24394A](https://img.shields.io/badge/%20-%20-24394A?style=flat-square) `#24394A` |
| Preview dark surface (1 use) | ![#111920](https://img.shields.io/badge/%20-%20-111920?style=flat-square) `#111920` | → | ![#122331](https://img.shields.io/badge/%20-%20-122331?style=flat-square) `#122331` |
| Optical viewport (1 use) | ![#05090D](https://img.shields.io/badge/%20-%20-05090D?style=flat-square) `#05090D` | → | ![#0A161F](https://img.shields.io/badge/%20-%20-0A161F?style=flat-square) `#0A161F` |
| Virtual preview surface (1 use) | ![#0D1721](https://img.shields.io/badge/%20-%20-0D1721?style=flat-square) `#0D1721` | → | ![#122333](https://img.shields.io/badge/%20-%20-122333?style=flat-square) `#122333` |
| Toast surface (2 uses) | ![#17202A](https://img.shields.io/badge/%20-%20-17202A?style=flat-square) `#17202A` | → | ![#162B3A](https://img.shields.io/badge/%20-%20-162B3A?style=flat-square) `#162B3A` |
| Plot text (light mode) (1 use) | ![#202832](https://img.shields.io/badge/%20-%20-202832?style=flat-square) `#202832` | → | ![#223340](https://img.shields.io/badge/%20-%20-223340?style=flat-square) `#223340` |
| Plot muted (light mode) (1 use) | ![#5E6975](https://img.shields.io/badge/%20-%20-5E6975?style=flat-square) `#5E6975` | → | ![#647D8C](https://img.shields.io/badge/%20-%20-647D8C?style=flat-square) `#647D8C` |
| Plot text (dark mode) (1 use) | ![#F3F6F8](https://img.shields.io/badge/%20-%20-F3F6F8?style=flat-square) `#F3F6F8` | → | ![#F2F7FA](https://img.shields.io/badge/%20-%20-F2F7FA?style=flat-square) `#F2F7FA` |
| Plot muted (dark mode) (1 use) | ![#C6CDD5](https://img.shields.io/badge/%20-%20-C6CDD5?style=flat-square) `#C6CDD5` | → | ![#C7D8E2](https://img.shields.io/badge/%20-%20-C7D8E2?style=flat-square) `#C7D8E2` |



## Audit references

- [Full context-by-context ledger, with selectors and line references at audit time](src/docs/HIF_COLOR_AUDIT_AND_MIGRATION.md)
- [Visual A → B SVG](src/docs/assets/HIF_COLOR_COMPARISON.svg)
- [Helmholtz 2012 design guideline](https://www.helmholtz.de/fileadmin/user_upload/05_aktuelles/Marke_Design/HG_Corporate_Design_Guidelines_120801.pdf)
- [HIF logo reference](https://commons.wikimedia.org/wiki/File:HIF_logo_GER_subline_below_blue_on_white_RGB.png)
