const path = require("node:path");

function engineSource(root) {
  return process.env.DAZEDTL_LEGACY_ROOT || path.resolve(root, "../DazedMTLTool-engine");
}

module.exports = { engineSource };
