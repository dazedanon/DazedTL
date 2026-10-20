/*:
 * @target MV MZ
 * @plugindesc メニューに冒険日誌を追加します。
 * @param command
 * @text コマンド名
 * @default 冒険日誌
 * @param empty
 * @text 空のときの文
 * @default まだ何も書かれていない。
 */
(function () {
  var parameters = PluginManager.parameters("MenuJournal");
  var addOriginalCommands = Window_MenuCommand.prototype.addOriginalCommands;
  Window_MenuCommand.prototype.addOriginalCommands = function () {
    addOriginalCommands.call(this);
    this.addCommand(parameters.command, "journal", true);
  };
  var createCommandWindow = Scene_Menu.prototype.createCommandWindow;
  Scene_Menu.prototype.createCommandWindow = function () {
    createCommandWindow.call(this);
    this._commandWindow.setHandler("journal", function () {
      $gameMessage.add(parameters.empty);
      SceneManager.goto(Scene_Map);
    });
  };
  // A label the plugin draws from its own code, not a parameter.
  var drawTitle = function (window) {
    window.drawText("日誌", 0, 0, window.contentsWidth());
  };
  Window_MenuCommand.prototype.journalTitle = function () {
    drawTitle(this);
  };
})();
