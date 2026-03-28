import React from 'react';

// Hardcoded section layout for a generic basketball arena.
// Each section has an (x, y) center on the 600x500 SVG viewBox.
const SECTION_POSITIONS = {
  // Lower bowl baseline (south)
  101: { x: 220, y: 395 }, 102: { x: 260, y: 405 }, 103: { x: 300, y: 410 },
  104: { x: 340, y: 405 }, 105: { x: 380, y: 395 },
  // Lower bowl east sideline
  106: { x: 430, y: 355 }, 107: { x: 455, y: 310 }, 108: { x: 462, y: 260 },
  109: { x: 455, y: 210 }, 110: { x: 430, y: 165 },
  // Lower bowl baseline (north)
  111: { x: 380, y: 125 }, 112: { x: 340, y: 115 }, 113: { x: 300, y: 110 },
  114: { x: 260, y: 115 }, 115: { x: 220, y: 125 },
  // Lower bowl west sideline
  116: { x: 170, y: 165 }, 117: { x: 145, y: 210 }, 118: { x: 138, y: 260 },
  119: { x: 145, y: 310 }, 120: { x: 170, y: 355 },
  // Upper deck
  201: { x: 215, y: 450 }, 202: { x: 300, y: 462 }, 203: { x: 385, y: 450 },
  204: { x: 490, y: 370 }, 205: { x: 520, y: 260 }, 206: { x: 490, y: 150 },
  207: { x: 385, y: 68 },  208: { x: 300, y: 56 },  209: { x: 215, y: 68 },
  210: { x: 110, y: 150 }, 211: { x: 80,  y: 260 }, 212: { x: 110, y: 370 },
};

function getDotColor(seat) {
  if (!seat) return null;
  return seat.type === 'real' ? '#00D4FF' : '#FF6B35';
}

export default function SeatMap({ seats, selectedSeatId, onSectionClick }) {
  // Build a map of section -> seat data for quick lookup
  const seatBySectionId = {};
  seats.forEach(s => { seatBySectionId[s.seatId] = s; });

  return (
    <svg
      viewBox="0 0 600 500"
      width="580"
      height="484"
      xmlns="http://www.w3.org/2000/svg"
      style={{ display: 'block' }}
    >
      <rect width="600" height="500" fill="#0A0A0F" />

      {/* Orientation labels */}
      <text x="300" y="24" fill="#2E2E44" fontSize="10" fontFamily="Geist Mono, monospace" textAnchor="middle">NORTH END</text>
      <text x="300" y="492" fill="#2E2E44" fontSize="10" fontFamily="Geist Mono, monospace" textAnchor="middle">SOUTH END</text>

      {/* Seating rings */}
      <ellipse cx="300" cy="260" rx="272" ry="218" fill="none" stroke="#1E1E2E" strokeWidth="1.5" />
      <ellipse cx="300" cy="260" rx="240" ry="190" fill="none" stroke="#1A1A24" strokeWidth="1" />
      <ellipse cx="300" cy="260" rx="208" ry="162" fill="none" stroke="#1A1A24" strokeWidth="1" />
      <ellipse cx="300" cy="260" rx="175" ry="135" fill="none" stroke="#1A1A24" strokeWidth="1" />
      <ellipse cx="300" cy="260" rx="142" ry="108" fill="none" stroke="#1E1E2E" strokeWidth="1.5" />

      {/* Section labels */}
      <text x="300" y="160" fill="#2E2E44" fontSize="9" fontFamily="Geist Mono, monospace" textAnchor="middle">200s</text>
      <text x="300" y="188" fill="#2E2E44" fontSize="9" fontFamily="Geist Mono, monospace" textAnchor="middle">100s</text>

      {/* Court */}
      <rect x="218" y="200" width="164" height="120" fill="#13131A" stroke="#2E2E44" strokeWidth="1" />
      <text x="300" y="263" fill="#2E2E44" fontSize="10" fontFamily="Geist Mono, monospace" textAnchor="middle">COURT</text>
      <path d="M 236 200 Q 300 228 364 200" fill="none" stroke="#1E1E2E" strokeWidth="1" />
      <path d="M 236 320 Q 300 292 364 320" fill="none" stroke="#1E1E2E" strokeWidth="1" />

      {/* Clickable sections */}
      {Object.entries(SECTION_POSITIONS).map(([sectionStr, pos]) => {
        const sectionNum = parseInt(sectionStr, 10);
        const seatId = String(sectionNum);
        const seat = seatBySectionId[seatId];
        const dotColor = getDotColor(seat);
        const isSelected = selectedSeatId === seatId;
        const isAI = seat && seat.type === 'ai';

        return (
          <g
            key={sectionStr}
            onClick={() => onSectionClick(sectionNum, pos)}
            style={{ cursor: 'pointer' }}
          >
            {/* Hit area */}
            <circle cx={pos.x} cy={pos.y} r={16} fill="transparent" />

            {/* Outer glow ring when selected */}
            {isSelected && (
              <circle cx={pos.x} cy={pos.y} r={18} fill="none" stroke="#FF6B35" strokeWidth={0.8} strokeDasharray="4,3" opacity={0.5} />
            )}

            {/* Pulse ring for real/AI dots */}
            {dotColor && (
              <circle cx={pos.x} cy={pos.y} r={12} fill="none" stroke={dotColor} strokeWidth={1} opacity={0.3}
                strokeDasharray={isAI ? '3,2' : undefined} />
            )}

            {/* Selection ring */}
            {isSelected && (
              <circle cx={pos.x} cy={pos.y} r={13} fill="none" stroke="#FF6B35" strokeWidth={1.5} opacity={0.9} />
            )}

            {/* Dot */}
            <circle
              cx={pos.x}
              cy={pos.y}
              r={6}
              fill={dotColor || 'transparent'}
              stroke={dotColor || '#2E2E44'}
              strokeWidth={dotColor ? 0 : 1}
              opacity={dotColor ? 0.9 : 0.6}
            />

            {/* Section label */}
            <text
              x={pos.x}
              y={pos.y + 18}
              fill={isSelected ? '#FF6B35' : dotColor || '#3A3A4A'}
              fontSize={8}
              fontFamily="Geist Mono, monospace"
              textAnchor="middle"
            >
              {sectionStr}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export { SECTION_POSITIONS };
