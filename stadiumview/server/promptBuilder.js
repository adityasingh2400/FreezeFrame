// Maps seat position to a Veo text prompt describing that view of the game.
// Section 100s = lower bowl, 200s = upper deck.
// Angle zones (by last 2 digits of section):
//   00-10 = south baseline
//   11-20 = east sideline
//   21-30 = north baseline
//   31-40 = west sideline

function getSeatDistance(section) {
  return section < 200 ? 'close to' : 'far from';
}

function getSeatAngle(section) {
  const s = section % 100;
  if (s <= 10) return 'south baseline';
  if (s <= 20) return 'east sideline';
  if (s <= 30) return 'north baseline';
  return 'west sideline';
}

function getSeatElevation(section, row) {
  if (section >= 200) return "high elevated bird's eye";
  if (row <= 5) return 'ground level';
  if (row <= 15) return 'slightly elevated';
  return 'elevated mid-level';
}

function buildVeoPrompt(section, row, sport = 'basketball') {
  const distance = getSeatDistance(section);
  const angle = getSeatAngle(section);
  const elevation = getSeatElevation(section, row);
  return (
    `${sport} game, live action, ${angle} view, ${elevation} angle, ` +
    `${distance} the court, fan perspective, stadium atmosphere, ` +
    `crowd cheering, authentic game footage style, 16:9 widescreen`
  );
}

module.exports = { buildVeoPrompt };
