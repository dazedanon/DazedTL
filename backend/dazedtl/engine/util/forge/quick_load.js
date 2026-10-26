// Forge's quick load replaces every game object and then leaves the current
// scene running while it fades out, so a map scene went on updating the loaded
// objects against the old map's data and could crash the game. Like the load
// screen, quick load now loads from a scene that updates no game objects, then
// goes to the map; a failed load returns to the scene it left.
(function () {
  var QuickLoadScene = null;
  function quickLoadScene() {
    if (QuickLoadScene) return QuickLoadScene;
    QuickLoadScene = function () {
      this.initialize.apply(this, arguments);
    };
    QuickLoadScene.prototype = Object.create(Scene_Base.prototype);
    QuickLoadScene.prototype.constructor = QuickLoadScene;
    QuickLoadScene.prototype.create = function () {
      Scene_Base.prototype.create.call(this);
      var background = SceneManager.backgroundBitmap();
      if (background) this.addChild(new Sprite(background));
    };
    QuickLoadScene.prototype.start = function () {
      Scene_Base.prototype.start.call(this);
      var scene = this;
      var request = QuickLoadScene.request;
      QuickLoadScene.request = null;
      function returnIfFailed() {
        if (SceneManager._scene === scene && !SceneManager.isSceneChanging()) {
          SceneManager.pop();
        }
      }
      Promise.resolve()
        .then(function () {
          return request.load(request.slot);
        })
        .then(returnIfFailed, returnIfFailed);
    };
    return QuickLoadScene;
  }
  // `load` is Forge's own quick load, which loads the slot and goes to the map.
  window.__dazedForgeQuickLoad = function (slot, load) {
    if (!window.SceneManager || !window.Scene_Base || !window.Sprite) {
      return load(slot);
    }
    var Scene = quickLoadScene();
    if (
      SceneManager._scene instanceof Scene ||
      SceneManager._nextScene instanceof Scene
    ) {
      return;
    }
    Scene.request = { slot: slot, load: load };
    SceneManager.snapForBackground();
    SceneManager.push(Scene);
  };
})();
