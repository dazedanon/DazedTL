// Electron work areas are already expressed in device-independent pixels.
function windowSize(workArea) {
  return {
    width: Math.min(1280, workArea.width),
    height: Math.min(880, workArea.height),
    minWidth: Math.min(900, workArea.width),
    minHeight: Math.min(520, workArea.height),
  };
}

module.exports = { windowSize };
