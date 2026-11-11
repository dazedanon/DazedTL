/*:
 * @target MV MZ
 * @plugindesc Shows the translation's title, game version and translator in the game window's title bar.
 * @author DazedTranslations
 *
 * @help DazedTLWindowTitle.js
 *
 * DazedTL writes this plugin and its title. The title bar shows the
 * parameter's text from boot on; the title the game draws on its title
 * screen, and the save folder, stay as they are. An empty title leaves the
 * game's own window title.
 *
 * @param title
 * @text Window title
 * @default
 */
(() => {
  "use strict";
  const parameters = PluginManager.parameters("DazedTLWindowTitle");
  const title = String(parameters.title || "");
  if (!title) return;
  Scene_Boot.prototype.updateDocumentTitle = function () {
    document.title = title;
  };
  document.title = title;
})();
