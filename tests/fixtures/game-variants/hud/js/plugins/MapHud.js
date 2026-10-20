/*:
 * @target MV MZ
 * @plugindesc A map HUD that draws the party's gold in its own window once a
 * message opens. Its text comes from no event, plugin text or translated data.
 */
(function () {
  function Window_MapHud() {
    this.initialize.apply(this, arguments);
  }
  Window_MapHud.prototype = Object.create(Window_Base.prototype);
  Window_MapHud.prototype.constructor = Window_MapHud;
  Window_MapHud.prototype.initialize = function () {
    if (Utils.RPGMAKER_NAME === "MZ")
      Window_Base.prototype.initialize.call(this, new Rectangle(0, 0, 240, 72));
    else Window_Base.prototype.initialize.call(this, 0, 0, 240, 72);
  };
  Window_MapHud.prototype.refresh = function () {
    this.contents.clear();
    this.drawText(
      $gameParty.gold() + " " + TextManager.currencyUnit,
      0,
      0,
      this.contentsWidth(),
    );
  };
  var createAllWindows = Scene_Map.prototype.createAllWindows;
  Scene_Map.prototype.createAllWindows = function () {
    createAllWindows.call(this);
    this._hudWindow = new Window_MapHud();
    this.addWindow(this._hudWindow);
  };
  var update = Scene_Map.prototype.update;
  Scene_Map.prototype.update = function () {
    update.call(this);
    if (this._messageWindow.isOpen() && !this._hudDrawn) {
      this._hudDrawn = true;
      this._hudWindow.refresh();
    }
  };
})();
