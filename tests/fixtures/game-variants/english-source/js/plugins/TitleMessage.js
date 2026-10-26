/*:
 * @target MZ
 * @plugindesc Shows a message on the title screen
 * @param text
 * @default Welcome
 */
(() => {
  const params = PluginManager.parameters("TitleMessage");
  console.log(params.text, "The adventure begins");
})();
