/*:
 * @target MZ
 * @plugindesc A map window that draws a game variable's name beside its value,
 * as variable window plugins do. Its show command names the variable.
 *
 * @command show
 * @text Show the window
 *
 * @arg variableId
 * @text Variable
 * @type variable
 * @default 0
 *
 * @command hide
 * @text Hide the window
 */
(function () {
  // MV has no plugin commands of this kind.
  if (Utils.RPGMAKER_NAME !== "MZ") return;
  var shown = 0;
  PluginManager.registerCommand("VariableWindow", "show", function (args) {
    shown = Number(args.variableId);
  });
  PluginManager.registerCommand("VariableWindow", "hide", function () {
    shown = 0;
  });
  function Window_Variable() {
    this.initialize.apply(this, arguments);
  }
  Window_Variable.prototype = Object.create(Window_Base.prototype);
  Window_Variable.prototype.constructor = Window_Variable;
  Window_Variable.prototype.update = function () {
    Window_Base.prototype.update.call(this);
    var text = shown
      ? $dataSystem.variables[shown] + "  " + $gameVariables.value(shown)
      : "";
    this.visible = shown > 0;
    if (text !== this._text) {
      this._text = text;
      this.contents.clear();
      this.drawText(text, 0, 0, this.contentsWidth());
    }
  };
  var createAllWindows = Scene_Map.prototype.createAllWindows;
  Scene_Map.prototype.createAllWindows = function () {
    createAllWindows.call(this);
    this._variableWindow = new Window_Variable(
      new Rectangle(Graphics.boxWidth - 400, 0, 400, 72),
    );
    this.addWindow(this._variableWindow);
  };
})();
