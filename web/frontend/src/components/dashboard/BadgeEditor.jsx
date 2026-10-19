import { KometaLanguageDemo, KometaRatingDemo, KometaTextDemo, LANGUAGE_PX, TEXT_BOX_PX, textBoxWidth } from './KometaDemo'

export default function BadgeEditor({ design, includeEpisodes }) {
  const {
    badgePositions, alignmentGuides, mediaOverlay, setMediaOverlay, ratingSources, badgeStyle, setBadgeStyle,
    savePositionsSoon, persistBadgeSettings, updateBadgeStyle, handleBadgeMouseDown, handlePosterMouseMove,
    handleMouseUp, setMediaPosition, setEpisodeOption, setRatingPosition,
  } = design
  // 'kometa' draws every badge like Kometa's defaults (fixed fonts, colors and sizes)
  const kometa = (badgeStyle.variant ?? badgeStyle.imdb_variant ?? 'kometa') === 'kometa'
  const kometaScale = (badgeStyle.kometa_scale ?? badgeStyle.imdb_scale ?? 100) / 100
  const topLogos = badgeStyle.top_logos ?? badgeStyle.imdb_top250_logo ?? true
  const labelOpacity = (badgeStyle.background_opacity ?? 215) / 255
  const labelColor = badgeStyle.rating_color || '#FFFFFF'
  const labelFontFamily = badgeStyle.font_family?.includes('Mono') ? 'monospace'
    : badgeStyle.font_family?.includes('Serif') ? 'serif' : 'sans-serif'
  const labelFontWeight = badgeStyle.font_family?.includes('Bold') ? 'bold' : 'normal'
  const labelFontStyle = /Oblique|Italic/.test(badgeStyle.font_family || '') ? 'italic' : 'normal'
  const labelFont = Math.max(3, 120 * (mediaOverlay.label_size_percent ?? mediaOverlay.font_percent ?? 4) / 100
    * (badgeStyle.font_size_multiplier ?? 1))

  const demoLabel = (key, value) => {
    if (kometa) {
      const status = key === 'status_position'
      const width = textBoxWidth(value, status) * kometaScale * .12
      const height = TEXT_BOX_PX.height * kometaScale * .12
      const pos = mediaOverlay[key] || {}
      const x = (pos.x ?? 30) / 1000 * 120
      const y = 180 - (pos.y ?? (status ? 120 : 30)) / 1500 * 180 - height
      return <KometaTextDemo key={key} text={value} status={status} unit={.12} scale={kometaScale}
        x={Math.max(0, Math.min(120 - width, x))} y={Math.max(0, Math.min(180 - height, y))}
        onMouseDown={e => handleBadgeMouseDown(e, key)} />
    }
    const width = labelFont * (String(value).length * .62 + .7)
    const height = labelFont * 1.6
    const pos = mediaOverlay[key] || {}
    const x = (pos.x ?? 30) / 1000 * 120
    const y = 180 - (pos.y ?? (key === 'status_position' ? 120 : 30)) / 1500 * 180 - height
    return <g key={key} transform={`translate(${Math.max(0, Math.min(120 - width, x))}, ${Math.max(0, Math.min(180 - height, y))})`}
      className="cursor-move" onMouseDown={e => handleBadgeMouseDown(e, key)}>
      <rect width={width} height={height} rx="2" fill="#0f1116" fillOpacity={labelOpacity} />
      <text x={labelFont * .3} y={labelFont * 1.17} fontSize={labelFont} fill={labelColor}
        fontFamily={labelFontFamily} fontWeight={labelFontWeight} fontStyle={labelFontStyle}>{value}</text>
    </g>
  }
  const episodeFont = Math.max(3, 192 * (mediaOverlay.episode_font_percent ?? 2.8) / 100
    * (badgeStyle.font_size_multiplier ?? 1))
  const episodePad = Math.max(1, episodeFont / 5)
  const episodeSourceText = mediaOverlay.source_labels?.bluray ?? 'BluRay'
  const episodeSourceWidth = episodeFont * (episodeSourceText.length * .62 + .7)
  const episodeSourceHeight = episodeFont * 1.6
  const episodeLanguageWidth = episodeFont * 3.8
  const episodeLanguageHeight = 2 * (episodeFont + episodePad) + episodePad

  return (
    <div>
      <label className="block text-sm font-medium mb-2">Badge Positions & Styling</label>
      <div className="bg-gray-900 rounded-lg p-4">
        <div className="flex flex-col md:flex-row md:items-start gap-6">
          {/* LEFT: Draggable Poster Preview */}
          <div className="flex-shrink-0">
            <svg
              viewBox="0 0 120 180"
              className="w-48 h-auto select-none"
              onMouseMove={handlePosterMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseUp}
            >
              {/* Poster Background */}
              <rect x="0" y="0" width="120" height="180" fill="#1f2937" stroke="#4b5563" strokeWidth="2" rx="3" />

              {/* Individual Badges - dynamically sized and styled */}
              {(() => {
                // Calculate badge dimensions based on style settings
                const badgeSizePercent = badgeStyle.individual_badge_size || 9
                const badgeWidth = (badgeSizePercent / 100) * 120  // Scale to SVG viewBox
                const badgeHeight = badgeWidth * 1.4  // 1.4 aspect ratio
                const logoMultiplier = badgeStyle.logo_size_multiplier || 2.0
                const fontMultiplier = badgeStyle.font_size_multiplier || 1.0
                // Logo occupies top 60% of badge, scaled by logo_size_multiplier (max 2.0 → full area)
                const logoAreaHeight = badgeHeight * 0.6 * Math.min(logoMultiplier / 2.0, 1.0)
                // Font size applies to bottom 40% (rating number), scaled by font_size_multiplier
                const fontSize = (badgeWidth / 14) * 8 * fontMultiplier
                const opacity = labelOpacity

                // Map font family to CSS font-family for SVG
                const getFontFamily = (fontName) => {
                  if (fontName.includes('Mono')) return 'monospace'
                  if (fontName.includes('Serif')) return 'serif'
                  return 'sans-serif'
                }

                const getFontStyle = (fontName) => {
                  return fontName.includes('Oblique') || fontName.includes('Italic') ? 'italic' : 'normal'
                }

                const getFontWeight = (fontName) => {
                  return fontName.includes('Bold') ? 'bold' : 'normal'
                }

                const fontFamily = getFontFamily(badgeStyle.font_family || 'Liberation Sans Bold')
                const fontStyle = getFontStyle(badgeStyle.font_family || 'DejaVu Sans Bold')
                const fontWeight = getFontWeight(badgeStyle.font_family || 'DejaVu Sans Bold')

                return (
                  <>
                    {!kometa && ratingSources.tmdb && badgePositions.tmdb && (
                      <g
                        className="cursor-move"
                        onMouseDown={(e) => handleBadgeMouseDown(e, 'tmdb')}
                      >
                        <rect x={(badgePositions.tmdb.x_px != null ? badgePositions.tmdb.x_px / 1000 * 120 : badgePositions.tmdb.x / 100 * 120)} y={(badgePositions.tmdb.y_px != null ? badgePositions.tmdb.y_px / 1500 * 180 : badgePositions.tmdb.y / 100 * 180)} width={badgeWidth} height={badgeHeight} fill="#000" fillOpacity={opacity} rx="2" />
                        <rect x={(badgePositions.tmdb.x_px != null ? badgePositions.tmdb.x_px / 1000 * 120 : badgePositions.tmdb.x / 100 * 120) + badgeWidth * 0.1} y={(badgePositions.tmdb.y_px != null ? badgePositions.tmdb.y_px / 1500 * 180 : badgePositions.tmdb.y / 100 * 180) + badgeHeight * 0.05} width={badgeWidth * 0.8} height={logoAreaHeight * 0.85} fill="#4a9eff" fillOpacity={0.35} rx="1" className="pointer-events-none" />
                        <text x={(badgePositions.tmdb.x_px != null ? badgePositions.tmdb.x_px / 1000 * 120 : badgePositions.tmdb.x / 100 * 120) + badgeWidth / 2} y={(badgePositions.tmdb.y_px != null ? badgePositions.tmdb.y_px / 1500 * 180 : badgePositions.tmdb.y / 100 * 180) + badgeHeight * 0.80} fontSize={fontSize} fill={badgeStyle.rating_color || '#FFD700'} textAnchor="middle" dominantBaseline="middle" fontFamily={fontFamily} fontStyle={fontStyle} fontWeight={fontWeight} className="pointer-events-none select-none">T</text>
                      </g>
                    )}

                    {kometa && ['tmdb', 'imdb', 'rt_critic', 'rt_audience'].filter(source => ratingSources[source] && badgePositions[source]).map(source =>
                      <KometaRatingDemo key={source} source={source} unit={120 / 1000} scale={kometaScale}
                        onMouseDown={(e) => handleBadgeMouseDown(e, source)}
                        x={badgePositions[source].x_px != null ? badgePositions[source].x_px / 1000 * 120 : badgePositions[source].x / 100 * 120}
                        y={badgePositions[source].y_px != null ? badgePositions[source].y_px / 1500 * 180 : badgePositions[source].y / 100 * 180} />)}
                    {ratingSources.imdb && badgePositions.imdb && !kometa && (
                      <g
                        className="cursor-move"
                        onMouseDown={(e) => handleBadgeMouseDown(e, 'imdb')}
                        transform={`translate(${badgePositions.imdb.x_px != null ? badgePositions.imdb.x_px / 1000 * 120 : badgePositions.imdb.x / 100 * 120}, ${badgePositions.imdb.y_px != null ? badgePositions.imdb.y_px / 1500 * 180 : badgePositions.imdb.y / 100 * 180})`}
                      >
                        <rect width={badgeWidth} height={badgeWidth * 1.04} fill="#0f1116" fillOpacity={(badgeStyle.background_opacity ?? 215) / 255} rx="2" />
                        <rect x={(badgeWidth - Math.min(badgeWidth * .45 * logoMultiplier, badgeWidth - 2)) / 2}
                          y={badgeWidth * .08} width={Math.min(badgeWidth * .45 * logoMultiplier, badgeWidth - 2)}
                          height={Math.min(badgeWidth * .21 * logoMultiplier, badgeWidth * .5)} fill="#f5c518" rx="1" />
                        <text x={badgeWidth / 2} y={badgeWidth * .29}
                          fontSize={badgeWidth * .23 * Math.min(logoMultiplier / 2, 1.4)} fill="#111"
                          textAnchor="middle" dominantBaseline="middle" fontFamily="sans-serif" fontWeight="bold"
                          className="pointer-events-none select-none">IMDb</text>
                        <text x={badgeWidth / 2} y={badgeWidth * .78} fontSize={badgeWidth * .31 * (badgeStyle.font_size_multiplier || 1)} fill={badgeStyle.rating_color || '#FFFFFF'} textAnchor="middle" dominantBaseline="middle" fontFamily={fontFamily} fontWeight="bold" className="pointer-events-none select-none">8.4</text>
                      </g>
                    )}

                    {!kometa && ratingSources.rt_critic && badgePositions.rt_critic && (
                      <g
                        className="cursor-move"
                        onMouseDown={(e) => handleBadgeMouseDown(e, 'rt_critic')}
                      >
                        <rect x={(badgePositions.rt_critic.x_px != null ? badgePositions.rt_critic.x_px / 1000 * 120 : badgePositions.rt_critic.x / 100 * 120)} y={(badgePositions.rt_critic.y_px != null ? badgePositions.rt_critic.y_px / 1500 * 180 : badgePositions.rt_critic.y / 100 * 180)} width={badgeWidth} height={badgeHeight} fill="#000" fillOpacity={opacity} rx="2" />
                        <rect x={(badgePositions.rt_critic.x_px != null ? badgePositions.rt_critic.x_px / 1000 * 120 : badgePositions.rt_critic.x / 100 * 120) + badgeWidth * 0.1} y={(badgePositions.rt_critic.y_px != null ? badgePositions.rt_critic.y_px / 1500 * 180 : badgePositions.rt_critic.y / 100 * 180) + badgeHeight * 0.05} width={badgeWidth * 0.8} height={logoAreaHeight * 0.85} fill="#fa320a" fillOpacity={0.35} rx="1" className="pointer-events-none" />
                        <text x={(badgePositions.rt_critic.x_px != null ? badgePositions.rt_critic.x_px / 1000 * 120 : badgePositions.rt_critic.x / 100 * 120) + badgeWidth / 2} y={(badgePositions.rt_critic.y_px != null ? badgePositions.rt_critic.y_px / 1500 * 180 : badgePositions.rt_critic.y / 100 * 180) + badgeHeight * 0.80} fontSize={fontSize} fill={badgeStyle.rating_color || '#FFD700'} textAnchor="middle" dominantBaseline="middle" fontFamily={fontFamily} fontStyle={fontStyle} fontWeight={fontWeight} className="pointer-events-none select-none">C</text>
                      </g>
                    )}

                    {!kometa && ratingSources.rt_audience && badgePositions.rt_audience && (
                      <g
                        className="cursor-move"
                        onMouseDown={(e) => handleBadgeMouseDown(e, 'rt_audience')}
                      >
                        <rect x={(badgePositions.rt_audience.x_px != null ? badgePositions.rt_audience.x_px / 1000 * 120 : badgePositions.rt_audience.x / 100 * 120)} y={(badgePositions.rt_audience.y_px != null ? badgePositions.rt_audience.y_px / 1500 * 180 : badgePositions.rt_audience.y / 100 * 180)} width={badgeWidth} height={badgeHeight} fill="#000" fillOpacity={opacity} rx="2" />
                        <rect x={(badgePositions.rt_audience.x_px != null ? badgePositions.rt_audience.x_px / 1000 * 120 : badgePositions.rt_audience.x / 100 * 120) + badgeWidth * 0.1} y={(badgePositions.rt_audience.y_px != null ? badgePositions.rt_audience.y_px / 1500 * 180 : badgePositions.rt_audience.y / 100 * 180) + badgeHeight * 0.05} width={badgeWidth * 0.8} height={logoAreaHeight * 0.85} fill="#fa320a" fillOpacity={0.25} rx="1" className="pointer-events-none" />
                        <text x={(badgePositions.rt_audience.x_px != null ? badgePositions.rt_audience.x_px / 1000 * 120 : badgePositions.rt_audience.x / 100 * 120) + badgeWidth / 2} y={(badgePositions.rt_audience.y_px != null ? badgePositions.rt_audience.y_px / 1500 * 180 : badgePositions.rt_audience.y / 100 * 180) + badgeHeight * 0.80} fontSize={fontSize} fill={badgeStyle.rating_color || '#FFD700'} textAnchor="middle" dominantBaseline="middle" fontFamily={fontFamily} fontStyle={fontStyle} fontWeight={fontWeight} className="pointer-events-none select-none">A</text>
                      </g>
                    )}
                  </>
                )
              })()}

              {mediaOverlay.source && demoLabel('source_position', mediaOverlay.source_labels?.bluray ?? 'BluRay')}
              {mediaOverlay.status && demoLabel('status_position', mediaOverlay.status_labels?.ended ?? 'Abgeschlossen')}

              {/* Alignment Guides */}
              {alignmentGuides.map((guide, index) => {
                if (guide.type === 'vertical') {
                  // Vertical line (for X-axis alignment)
                  const x = (guide.position / 100) * 120
                  return (
                    <line
                      key={`guide-${index}`}
                      x1={x}
                      y1={0}
                      x2={x}
                      y2={180}
                      stroke="#3b82f6"
                      strokeWidth="1"
                      strokeDasharray="4,4"
                      className="pointer-events-none"
                    />
                  )
                } else {
                  // Horizontal line (for Y-axis alignment)
                  const y = (guide.position / 100) * 180
                  return (
                    <line
                      key={`guide-${index}`}
                      x1={0}
                      y1={y}
                      x2={120}
                      y2={y}
                      stroke="#3b82f6"
                      strokeWidth="1"
                      strokeDasharray="4,4"
                      className="pointer-events-none"
                    />
                  )
                }
              })}
            </svg>
            {(includeEpisodes || mediaOverlay.languages) && (
              <div className="mt-3">
                <div className="text-xs text-gray-400 mb-1">Episodenbild (16:9): Sprachen untereinander</div>
                <svg viewBox="0 0 192 108" className="w-48 h-auto select-none"
                  aria-label="Episoden-Vorschau" onMouseMove={e => handlePosterMouseMove(e, true)}
                  onMouseUp={handleMouseUp} onMouseLeave={handleMouseUp}>
                  <rect width="192" height="108" rx="3" fill="#1f2937" stroke="#4b5563" />
                  {ratingSources.imdb && kometa && <KometaRatingDemo source="imdb" unit={192 / 1920} scale={kometaScale}
                    onMouseDown={e => handleBadgeMouseDown(e, 'imdb')}
                    x={(badgePositions.imdb?.x_px ?? (badgePositions.imdb?.x ?? 2) * 19.2) / 10}
                    y={(badgePositions.imdb?.y_px ?? (badgePositions.imdb?.y ?? 2) * 10.8) / 10} />}
                  {ratingSources.imdb && !kometa && <g className="cursor-move" onMouseDown={e => handleBadgeMouseDown(e, 'imdb')}
                    transform={`translate(${(badgePositions.imdb?.x_px ?? (badgePositions.imdb?.x ?? 2) * 19.2) / 10}, ${(badgePositions.imdb?.y_px ?? (badgePositions.imdb?.y ?? 2) * 10.8) / 10})`}>
                    <rect width={(mediaOverlay.episode_badge_percent ?? 9) / 100 * 192}
                      height={(mediaOverlay.episode_badge_percent ?? 9) / 100 * 192 * 1.04}
                      rx="2" fill="#0f1116" fillOpacity={labelOpacity} />
                    <rect x="1" y="1" width={(mediaOverlay.episode_badge_percent ?? 9) / 100 * 192 - 2}
                      height={(mediaOverlay.episode_badge_percent ?? 9) / 100 * 192 * .42}
                      rx="1" fill="#f5c518" />
                    <text x={(mediaOverlay.episode_badge_percent ?? 9) / 100 * 96} y="7" textAnchor="middle"
                      fontSize="4" fontWeight="bold" fill="#111">IMDb</text>
                    <text x={(mediaOverlay.episode_badge_percent ?? 9) / 100 * 96}
                      y={(mediaOverlay.episode_badge_percent ?? 9) / 100 * 192 * .82}
                      textAnchor="middle" fontSize={(mediaOverlay.episode_badge_percent ?? 9) / 100 * 192 * .31
                        * (badgeStyle.font_size_multiplier ?? 1)} fontFamily={labelFontFamily}
                      fontWeight={labelFontWeight} fill={labelColor}>8.4</text>
                  </g>}
                  {kometa && mediaOverlay.source && <KometaTextDemo text={episodeSourceText} unit={.1} scale={kometaScale}
                    onMouseDown={e => handleBadgeMouseDown(e, 'source_position')}
                    x={(mediaOverlay.source_position?.x ?? 30) / 10}
                    y={108 - (mediaOverlay.source_position?.y ?? 30) / 10 - TEXT_BOX_PX.height * kometaScale * .1} />}
                  {kometa && mediaOverlay.languages && <KometaLanguageDemo codes={['DE', 'EN']} unit={.1} scale={kometaScale}
                    englishFlag={mediaOverlay.episode_english_flag}
                    onMouseDown={e => handleBadgeMouseDown(e, 'languages_position')}
                    x={192 - (mediaOverlay.languages_position?.x ?? 30) / 10 - LANGUAGE_PX.width * kometaScale * .1}
                    y={108 - (mediaOverlay.languages_position?.y ?? 30) / 10 - (LANGUAGE_PX.spacing + LANGUAGE_PX.height) * kometaScale * .1} />}
                  {!kometa && mediaOverlay.source && <g className="cursor-move" onMouseDown={e => handleBadgeMouseDown(e, 'source_position')}
                    transform={`translate(${(mediaOverlay.source_position?.x ?? 30) / 10}, ${108 - (mediaOverlay.source_position?.y ?? 30) / 10 - episodeSourceHeight})`}>
                    <rect width={episodeSourceWidth} height={episodeSourceHeight} rx="2"
                      fill="#0f1116" fillOpacity={labelOpacity} />
                    <text x={episodeFont * .3} y={episodeFont * 1.17} fontSize={episodeFont}
                      fontFamily={labelFontFamily} fontWeight={labelFontWeight} fontStyle={labelFontStyle}
                      fill={labelColor}>{episodeSourceText}</text>
                  </g>}
                  {!kometa && mediaOverlay.languages && <g className="cursor-move" onMouseDown={e => handleBadgeMouseDown(e, 'languages_position')}
                    transform={`translate(${192 - (mediaOverlay.languages_position?.x ?? 30) / 10 - episodeLanguageWidth}, ${108 - (mediaOverlay.languages_position?.y ?? 30) / 10 - episodeLanguageHeight})`}>
                    <rect width={episodeLanguageWidth} height={episodeLanguageHeight} rx="2"
                      fill="#0f1116" fillOpacity={labelOpacity} />
                    {['DE', 'EN'].map((code, row) => <g key={code}
                      transform={`translate(${episodePad}, ${episodePad + row * (episodeFont + episodePad)})`}>
                      <text x="0" y={episodeFont * .85} fontSize={episodeFont * .85} fill="white">
                        {code === 'DE' ? '🇩🇪' : mediaOverlay.episode_english_flag === 'GB' ? '🇬🇧' : '🇺🇸'}
                      </text>
                      <text x={episodeFont * 1.4} y={episodeFont * .85} fontSize={episodeFont}
                        fontFamily={labelFontFamily} fontWeight={labelFontWeight}
                        fontStyle={labelFontStyle} fill={labelColor}>{code}</text>
                    </g>)}
                  </g>}
                </svg>
              </div>
            )}
            <div className="text-xs text-gray-500 mt-2 space-y-1">
              <p className="font-medium">💡 Drag badges to position</p>
              {!kometa && <div className="text-gray-400 leading-relaxed">
                <span className="font-bold text-white">T</span>=<span className="font-bold">TMDB</span> • <span className="font-bold text-white">I</span>=<span className="font-bold">IMDb</span> • <span className="font-bold text-white">C</span>=<span className="font-bold">RT Critic</span> • <span className="font-bold text-white">A</span>=<span className="font-bold">RT Audience</span>
              </div>}
            </div>
          </div>

          {/* RIGHT: Styling Controls */}
          <div className="flex-1 min-w-0 w-full space-y-3">
            <div className="border-b border-gray-700 pb-4 space-y-3">
              <h3 className="text-sm font-medium">Positionen direkt auf den Demos ziehen oder per Slider einstellen</h3>
              {[
                ['IMDb', 'imdb', ratingSources.imdb], ['TMDB', 'tmdb', ratingSources.tmdb],
                ['RT Critic', 'rt_critic', ratingSources.rt_critic],
                ['RT Audience', 'rt_audience', ratingSources.rt_audience],
                ['BluRay / PreRelease', 'source_position', mediaOverlay.source],
                ['Serienstatus', 'status_position', mediaOverlay.status],
                ['Episodensprachen', 'languages_position', mediaOverlay.languages],
              ].filter(([, , enabled]) => enabled).map(([label, key]) => (
                <div key={key} className="text-xs text-gray-300">
                  <div className="mb-1">{label}</div>
                  {['x', 'y'].map(axis => {
                    const rating = !key.endsWith('_position')
                    const current = rating
                      ? badgePositions[key]?.[`${axis}_px`] ?? Math.round((badgePositions[key]?.[axis] ?? 2) * (axis === 'x' ? 10 : 15))
                      : mediaOverlay[key]?.[axis] ?? (key === 'status_position' && axis === 'y' ? 120 : 30)
                    return <label key={axis} className="flex items-center gap-2">
                      <span className="uppercase w-3">{axis}</span>
                      <input type="range" min="0" max="2000" step="1" value={current}
                        onChange={e => rating ? setRatingPosition(key, axis, e.target.value) : setMediaPosition(key, axis, e.target.value)}
                        className="flex-1 accent-blue-500" />
                      <input type="number" min="0" max="2000" value={current}
                        onChange={e => rating ? setRatingPosition(key, axis, e.target.value) : setMediaPosition(key, axis, e.target.value)}
                        className="w-16 bg-gray-800 border border-gray-700 rounded px-1 py-1 text-white" />px
                    </label>
                  })}
                </div>
              ))}
            </div>
            <div className="border-b border-gray-700 pb-3 space-y-2">
              <label className="text-xs text-gray-400 block">Badge-Stil
                <select value={kometa ? 'kometa' : 'compact'} onChange={e => updateBadgeStyle('variant', e.target.value)}
                  className="mt-1 block w-full px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-white">
                  <option value="kometa">Wie Kometa</option>
                  <option value="compact">Kompakt (frei gestaltbar)</option>
                </select>
              </label>
              {/* Short options: Safari sizes a select by its longest option and would widen the page on phones */}
              <p className="text-xs text-gray-500">{kometa ? 'Logos, Schrift Inter, Boxen und Farben aus Kometas Standard-Overlays.' : 'Bisherige Kometizarr-Darstellung, Schrift, Farben und Größen frei einstellbar.'}</p>
              {kometa && <>
                <label className="text-xs text-gray-400 block">Größe aller Badges: {Math.round(kometaScale * 100)}% von Kometa
                  <input type="range" min="50" max="200" step="5" value={Math.round(kometaScale * 100)}
                    onChange={e => updateBadgeStyle('kometa_scale', Number(e.target.value))} className="w-full accent-blue-500" />
                </label>
                <label className="text-xs text-gray-300 flex items-center gap-2">
                  <input type="checkbox" checked={topLogos}
                    onChange={e => updateBadgeStyle('top_logos', e.target.checked)} />
                  Kometas Top-Logos: IMDb Top 250, RT Certified Fresh und Verified Hot
                </label>
                <p className="text-xs text-gray-500">Schrift, Farben, Hintergrund und Boxgrößen kommen im Kometa-Stil aus Kometas Vorlagen; die Regler dafür sind ausgeblendet.</p>
              </>}
            </div>
            {!kometa && <>
            {/* Badge Size */}
            <div>
              <label className="text-xs text-gray-400 block mb-1">
                Rating-Badges: {badgeStyle.individual_badge_size}% der Posterbreite
              </label>
              <input
                type="range"
                min="5"
                max="30"
                step="1"
                value={badgeStyle.individual_badge_size}
                onChange={(e) => updateBadgeStyle('individual_badge_size', parseInt(e.target.value))}
                className="w-full accent-blue-500"
              />
            </div>

            <div>
              <label className="text-xs text-gray-400 block mb-1">
                Text-Badges (BluRay / Status): {mediaOverlay.label_size_percent ?? mediaOverlay.font_percent ?? 4}% der Posterbreite
              </label>
              <input type="range" min="1" max="12" step="0.1"
                value={mediaOverlay.label_size_percent ?? mediaOverlay.font_percent ?? 4}
                onChange={e => setEpisodeOption('label_size_percent', e.target.value)}
                className="w-full accent-blue-500" />
            </div>

            </>}

            <div className="border-t border-gray-700 pt-3 space-y-2">
              <div className="text-xs font-medium text-gray-300">Episoden-Demo (16:9)</div>
              {[
                ['IMDb-Badge', 'episode_badge_percent', 5, 20, 1, 9],
                ['Text und Flaggen', 'episode_font_percent', 1, 7, .1, 2.8],
                ['Randabstand ohne Positionswert', 'episode_edge_percent', 0, 6, .1, 1.2],
              ].filter(([, key]) => !kometa || key === 'episode_edge_percent').map(([label, key, min, max, step, fallback]) => (
                <label key={key} className="block text-xs text-gray-400">
                  {label}: {mediaOverlay[key] ?? fallback}% der Bildbreite
                  <input type="range" min={min} max={max} step={step}
                    value={mediaOverlay[key] ?? fallback}
                    onChange={e => setEpisodeOption(key, e.target.value)}
                    className="w-full accent-blue-500" />
                </label>
              ))}
              <label className="text-xs text-gray-400 flex items-center gap-2">EN-Flagge
                <select value={mediaOverlay.episode_english_flag ?? 'US'}
                  onChange={e => {
                    const next = { ...mediaOverlay, episode_english_flag: e.target.value }
                    setMediaOverlay(next)
                    savePositionsSoon({ media_overlay: next })
                  }} className="bg-gray-800 border border-gray-700 rounded p-1">
                  <option value="US">🇺🇸 US</option><option value="GB">🇬🇧 GB</option>
                </select>
              </label>
            </div>

            {!kometa && <>
            {/* Font Size */}
            <div>
              <label className="text-xs text-gray-400 block mb-1">
                Font Size: {badgeStyle.font_size_multiplier.toFixed(1)}x
              </label>
              <input
                type="range"
                min="0.5"
                max="2.0"
                step="0.05"
                value={badgeStyle.font_size_multiplier}
                onChange={(e) => updateBadgeStyle('font_size_multiplier', parseFloat(e.target.value))}
                className="w-full accent-blue-500"
              />
            </div>

            {/* Logo Size */}
            <div>
              <label className="text-xs text-gray-400 block mb-1">
                Logo Size: {((badgeStyle.logo_size_multiplier || 2.0) / 2).toFixed(1)}x
              </label>
              <input
                type="range"
                min="0.25"
                max="3.0"
                step="0.1"
                value={(badgeStyle.logo_size_multiplier || 2.0) / 2}
                onChange={(e) => updateBadgeStyle('logo_size_multiplier', parseFloat(e.target.value) * 2)}
                className="w-full accent-blue-500"
              />
            </div>

            {/* Font and Color - Side by Side */}
            <div className="grid grid-cols-2 gap-3">
              {/* Font Family */}
              <div>
                <label className="text-xs text-gray-400 block mb-1">
                  Font
                </label>
                <select
                  value={badgeStyle.font_family}
                  onChange={(e) => updateBadgeStyle('font_family', e.target.value)}
                  className="w-full px-2 py-1.5 bg-gray-800 border border-gray-700 rounded text-sm text-white"
                >
                  <option value="Liberation Sans Bold">Arial-like Bold (reference)</option>
                  <option value="DejaVu Sans Bold">DejaVu Sans Bold</option>
                  <option value="DejaVu Sans">Sans Regular</option>
                  <option value="DejaVu Sans Bold Oblique">Sans Bold Italic</option>
                  <option value="DejaVu Sans Oblique">Sans Italic</option>
                  <option value="DejaVu Serif Bold">Serif Bold</option>
                  <option value="DejaVu Serif">Serif Regular</option>
                  <option value="DejaVu Serif Bold Italic">Serif Bold Italic</option>
                  <option value="DejaVu Serif Italic">Serif Italic</option>
                  <option value="DejaVu Sans Mono Bold">Mono Bold</option>
                  <option value="DejaVu Sans Mono">Mono Regular</option>
                  <option value="DejaVu Sans Mono Oblique">Mono Italic</option>
                </select>
              </div>

              {/* Rating Color */}
              <div>
                <label className="text-xs text-gray-400 block mb-1">
                  Color
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="color"
                    value={badgeStyle.rating_color}
                    onChange={(e) => updateBadgeStyle('rating_color', e.target.value)}
                    className="w-10 h-8 rounded border border-gray-700 bg-gray-800 cursor-pointer"
                  />
                  <span className="text-xs text-gray-400 font-mono text-xs">{badgeStyle.rating_color}</span>
                </div>
              </div>
            </div>

            {/* Background Opacity */}
            <div>
              <label className="text-xs text-gray-400 block mb-1">
                Background: {Math.round((badgeStyle.background_opacity / 255) * 100)}%
              </label>
              <input
                type="range"
                min="0"
                max="255"
                step="5"
                value={badgeStyle.background_opacity}
                onChange={(e) => updateBadgeStyle('background_opacity', parseInt(e.target.value))}
                className="w-full accent-blue-500"
              />
            </div>

            </>}

            {/* Reset Button */}
            <button
              onClick={() => {
                const defaults = {
                  individual_badge_size: 9,
                  font_size_multiplier: 1.0,
                  logo_size_multiplier: 2.0,
                  rating_color: '#FFFFFF',
                  background_opacity: 215,
                  font_family: 'Liberation Sans Bold'
                }
                setBadgeStyle(defaults)
                const mediaDefaults = { ...mediaOverlay, label_size_percent: 4, episode_font_percent: 2.8,
                  episode_badge_percent: 9 }
                setMediaOverlay(mediaDefaults)
                localStorage.setItem('kometizarr_badge_style', JSON.stringify(defaults))
                persistBadgeSettings({ badge_style: defaults, media_overlay: mediaDefaults })
              }}
              className="w-full text-xs px-3 py-1.5 bg-gray-800 hover:bg-gray-700 rounded border border-gray-700 transition"
            >
              ↺ Apply reference defaults
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
