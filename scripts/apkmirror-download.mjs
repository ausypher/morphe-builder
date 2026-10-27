import { readdir } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const [installDir, org, repo, version, arch, dpi, type] = process.argv.slice(2);
if (![installDir, org, repo, version, arch, dpi, type].every(Boolean)) {
  console.error("Usage: node scripts/apkmirror-download.mjs INSTALL_DIR ORG REPO VERSION ARCH DPI TYPE");
  process.exit(2);
}

const modulePath = pathToFileURL(resolve(installDir, "node_modules/apkmirror-downloader/dist/index.js")).href;
const { APKMirrorDownloader } = await import(modulePath);
const downloader = new APKMirrorDownloader({ outDir: installDir });
await downloader.download(
  { org, repo },
  { version, arch, dpi, type, outDir: installDir, outFile: "download" }
);

const files = await readdir(installDir);
const candidates = files.filter((name) => /^download(?:\.|$)/.test(name));
if (!candidates.length) {
  console.error("APKMirror Downloader finished without producing download.*");
  process.exit(1);
}
console.log("APKMirror Downloader output:", candidates.join(", "));
