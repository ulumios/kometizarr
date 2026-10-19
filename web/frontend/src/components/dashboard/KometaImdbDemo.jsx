// SVG preview of the IMDb badge exactly as Kometa draws it (see create_kometa_imdb_badge):
// 160x160 box + 15 padding, radius 30, #00000099, IMDb image 149x75 above the score
// (Inter Bold 63, white). Sizes are canvas pixels; `unit` converts them to SVG units.
export const KOMETA_BADGE_PX = 191

export default function KometaImdbDemo({ x, y, unit, scale = 1, top250 = false, onMouseDown }) {
  const s = unit * scale
  const textHeight = 46, imageWidth = 149, imageHeight = 75, gap = 15
  const top = 15 + (160 - (textHeight + imageHeight + gap)) / 2
  return <g className="cursor-move" onMouseDown={onMouseDown} transform={`translate(${x}, ${y})`}>
    <rect width={KOMETA_BADGE_PX * s} height={KOMETA_BADGE_PX * s} rx={30 * s} fill="#000" fillOpacity={0x99 / 255} />
    <rect x={(15 + (160 - imageWidth) / 2) * s} y={top * s} width={imageWidth * s} height={imageHeight * s}
      rx={14 * s} fill="#f5c518" />
    <text x={95.5 * s} y={(top + imageHeight / 2) * s} fontSize={56 * s} fill="#000" textAnchor="middle"
      dominantBaseline="central" fontFamily="Impact, 'Arial Black', sans-serif" fontWeight="bold"
      className="pointer-events-none select-none">{top250 ? '250' : 'IMDb'}</text>
    <text x={95.5 * s} y={(top + imageHeight + gap + textHeight / 2) * s} fontSize={63 * s} fill="#fff"
      textAnchor="middle" dominantBaseline="central" fontFamily="Inter, sans-serif" fontWeight="bold"
      className="pointer-events-none select-none">8.4</text>
  </g>
}
