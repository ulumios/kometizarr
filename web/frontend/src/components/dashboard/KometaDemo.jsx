// SVG previews of Kometa's default overlays, sized like kometa_style.py (canvas pixels;
// `unit` converts canvas pixels to SVG units, `scale` is the Kometa size factor).

const BACK = { fill: '#000', fillOpacity: 0x99 / 255 }
export const RATING_PX = 191                     // 160 box + 2 x 15 padding + 1
export const TEXT_BOX_PX = { width: 305, height: 105 }
export const LANGUAGE_PX = { width: 190, height: 60, spacing: 61 }

// Width of a Kometa text box: 305 px, wider for long labels (Inter Medium ~0.56 em per char)
export const textBoxWidth = (text, status = false) =>
  Math.max(305, String(text).length * (status ? 50 : 55) * 0.56 + 40)

const LOGOS = {
  imdb: { fill: '#f5c518', text: 'IMDb', color: '#000', width: 149 },
  tmdb: { fill: '#01b4e4', text: 'TMDB', color: '#fff', width: 144 },
  rt_critic: { fill: '#fa320a', text: 'RT', color: '#fff', width: 80, round: true },
  rt_audience: { fill: '#fa320a', text: '🍿', color: '#fff', width: 80 },
}
const SAMPLE = { imdb: '8.4', tmdb: '74%', rt_critic: '92%', rt_audience: '88%' }

export function KometaRatingDemo({ source, x, y, unit, scale = 1, onMouseDown }) {
  const s = unit * scale
  const logo = LOGOS[source]
  const height = source.startsWith('rt_') ? 80 : 75
  const top = 15 + (160 - (46 + height + 15)) / 2
  return <g className="cursor-move" onMouseDown={onMouseDown} transform={`translate(${x}, ${y})`}>
    <rect width={RATING_PX * s} height={RATING_PX * s} rx={30 * s} {...BACK} />
    <rect x={(95.5 - logo.width / 2) * s} y={top * s} width={logo.width * s} height={height * s}
      rx={(logo.round ? 40 : 14) * s} fill={logo.fill} />
    <text x={95.5 * s} y={(top + height / 2) * s} fontSize={(logo.round ? 40 : 52) * s} fill={logo.color}
      textAnchor="middle" dominantBaseline="central" fontFamily="Impact, 'Arial Black', sans-serif" fontWeight="bold"
      className="pointer-events-none select-none">{logo.text}</text>
    <text x={95.5 * s} y={(top + height + 15 + 23) * s} fontSize={63 * s} fill="#fff" textAnchor="middle"
      dominantBaseline="central" fontFamily="Inter, sans-serif" fontWeight="bold"
      className="pointer-events-none select-none">{SAMPLE[source]}</text>
  </g>
}

export function KometaTextDemo({ text, x, y, unit, scale = 1, status = false, onMouseDown }) {
  const s = unit * scale
  const width = textBoxWidth(text, status)
  return <g className="cursor-move" onMouseDown={onMouseDown} transform={`translate(${x}, ${y})`}>
    <rect width={width * s} height={TEXT_BOX_PX.height * s} rx={30 * s} {...BACK} />
    <text x={width / 2 * s} y={52.5 * s} fontSize={(status ? 50 : 55) * s} fill="#fff" textAnchor="middle"
      dominantBaseline="central" fontFamily="Inter, sans-serif" fontWeight="500"
      className="pointer-events-none select-none">{text}</text>
  </g>
}

export function KometaLanguageDemo({ codes, englishFlag = 'US', x, y, unit, scale = 1, onMouseDown }) {
  const s = unit * scale
  const flags = { DE: '🇩🇪', EN: englishFlag === 'GB' ? '🇬🇧' : '🇺🇸' }
  return <g className="cursor-move" onMouseDown={onMouseDown} transform={`translate(${x}, ${y})`}>
    {codes.map((code, row) => <g key={code} transform={`translate(0, ${row * LANGUAGE_PX.spacing * s})`}>
      <rect width={LANGUAGE_PX.width * s} height={LANGUAGE_PX.height * s} rx={26 * s} {...BACK} />
      <text x={51 * s} y={30 * s} fontSize={52 * s} textAnchor="middle" dominantBaseline="central"
        className="pointer-events-none select-none">{flags[code] || '🏳️'}</text>
      <text x={112 * s} y={30 * s} fontSize={50 * s} fill="#fff" dominantBaseline="central"
        fontFamily="Inter, sans-serif" fontWeight="bold" className="pointer-events-none select-none">{code}</text>
    </g>)}
  </g>
}
