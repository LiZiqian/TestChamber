const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..", "..");
const appCorePath = path.join(root, "frontend", "js", "app.core.js");
const versionText = fs.readFileSync(path.join(root, "VERSION"), "utf8").trim();
const appCoreCode = fs.readFileSync(appCorePath, "utf8");

function loadAppVersionFromMeta(metaValue) {
  const context = {
    console,
    setTimeout,
    clearTimeout,
    alert: () => {},
    document: {
      querySelector(selector) {
        assert.equal(selector, 'meta[name="testchamber-version"]');
        if (metaValue === null) return null;
        return {
          getAttribute(name) {
            assert.equal(name, "content");
            return metaValue;
          },
        };
      },
      addEventListener: () => {},
    },
    window: {},
  };
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(`${appCoreCode}\nglobalThis.loadedAppVersion = app.version;`, context, { filename: "frontend/js/app.core.js" });
  return context.loadedAppVersion;
}

assert.equal(loadAppVersionFromMeta(versionText), versionText);
assert.equal(loadAppVersionFromMeta(null), "dev");
assert.equal(loadAppVersionFromMeta(" 7.2.0 "), "7.2.0");
console.log("frontend app version tests passed");
