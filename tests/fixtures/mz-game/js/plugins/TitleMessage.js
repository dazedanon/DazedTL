/*:
 * @target MZ
 * @plugindesc タイトルに文章を表示します
 * @param text
 * @default ようこそ
 */
(() => {
  const params = PluginManager.parameters('TitleMessage');
  console.log(params.text, '冒険の始まり');
})();
