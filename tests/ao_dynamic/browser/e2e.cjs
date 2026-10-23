// Browser end-to-end checks of the generated-experiment mode against a real
// computation service.  The page is served by a separate static server (as a
// published site would be) and talks to the service cross-origin.
//
// Usage: NODE_PATH=<global node_modules> node e2e.cjs <static-base> <service-base> <out-dir>
// Prints one JSON line {ok, scenarios, ...}; exits non-zero on the first failure.
"use strict";
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");

const [staticBase, serviceBase, outDir] = process.argv.slice(2);
const executablePath = process.env.CHROMIUM_EXECUTABLE || undefined;
const results = [];
const pageErrors = [];
const page_url = (query = "") => `${staticBase}/ao-explorer/${query}`;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function newPage(browser, options = {}) {
  const context = await browser.newContext({ viewport: { width: 1200, height: 900 }, ...options });
  const page = await context.newPage();
  page.on("pageerror", (error) => pageErrors.push(error.message));
  return { context, page };
}

const text = (page, selector) => page.textContent(selector);
async function waitText(page, selector, predicate, timeout = 60000) {
  await page.waitForFunction(([sel, source]) => {
    const element = document.querySelector(sel);
    // eslint-disable-next-line no-new-func
    return element && new Function("t", `return (${source})(t);`)(element.textContent);
  }, [selector, predicate.toString()], { timeout });
  return text(page, selector);
}
async function connected(page) { return waitText(page, "#gen-conn-state", (t) => t.startsWith("Connected")); }
async function installedRun(page, previous = null) {
  await page.waitForFunction((prev) => {
    const t = document.getElementById("gen-run-id").textContent;
    return t.startsWith("run-") && !t.startsWith(prev || "\u0000");
  }, previous, { timeout: 90000 });
  return (await text(page, "#gen-run-id")).split(" ")[0];
}
async function setParams(page, values) {
  for (const [name, value] of Object.entries(values)) await page.fill(`#gen-p-${name}`, String(value));
}
async function openRunList(page) {
  await page.evaluate(() => { document.getElementById("gen-runs").closest("details").open = true; });
  await page.click("#gen-runs-refresh");
}
async function canvasInk(page, id) {
  return page.evaluate((canvasId) => {
    const c = document.getElementById(canvasId); const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
    let opaque = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) opaque += 1;
    return opaque / (c.width * c.height);
  }, id);
}
async function serviceStatus(runId) {
  const response = await fetch(`${serviceBase}/api/v1/runs/${runId}`);
  return response.json();
}
async function scenario(name, body) {
  const started = Date.now();
  await body();
  results.push({ name, seconds: (Date.now() - started) / 1000 });
}

(async () => {
  const browser = await chromium.launch(executablePath ? { executablePath } : {});
  const runs = {};

  await scenario("static mode makes no computation-service request", async () => {
    const { context, page } = await newPage(browser);
    const urls = [];
    page.on("request", (request) => urls.push(request.url()));
    await page.goto(page_url());
    await waitText(page, "#status", (t) => t.startsWith("Showing"));
    await page.evaluate(() => document.getElementById("results").scrollIntoView());
    await waitText(page, "#results-status", (t) => t.startsWith("Eight result groups"));
    assert.ok(urls.every((u) => !u.includes("/api/") && !u.includes("generate")), urls.filter((u) => u.includes("generate") || u.includes("/api/")).join(" "));
    assert.match(await text(page, "#gen-conn-state"), /^Not connected/);
    assert.equal(await page.isHidden("#gen-app"), true);
    assert.ok(urls.some((u) => /code-[0-9a-f]{16}\/app\.js$/.test(u)));
    await context.close();
  });

  await scenario("unreachable and incompatible services are refused readably", async () => {
    const { context, page } = await newPage(browser);
    await page.goto(page_url("#generate"));
    await page.fill("#gen-url", "http://127.0.0.1:9");
    await page.click("#gen-connect");
    await waitText(page, "#gen-conn-state", (t) => t.startsWith("Could not reach"));
    await page.route(`${serviceBase}/api/v1/info`, async (route) => {
      const response = await route.fetch();
      const info = await response.json();
      info.api = "ao-dynamic.api.v2";
      await route.fulfill({ response, json: info });
    });
    await page.fill("#gen-url", serviceBase);
    await page.click("#gen-connect");
    await waitText(page, "#gen-conn-state", (t) => t.includes("not compatible"));
    assert.match(await text(page, "#gen-error"), /needs ao-dynamic\.api\.v1/);
    assert.equal(await page.isHidden("#gen-app"), true);
    assert.match(await text(page, "#status"), /^Showing/);
    await context.close();
  });

  const { context, page } = await newPage(browser);
  await scenario("cross-origin connect, run, verify and replay", async () => {
    await page.goto(page_url(`?backend=${encodeURIComponent(serviceBase)}#generate`));
    await connected(page);
    await setParams(page, { n_frames: 24, burn_in: 8, display_stride: 2 });
    assert.match(await text(page, "#gen-hints"), /13 of 24 frames would be kept/);
    await page.click("#gen-run");
    runs.A = await installedRun(page);
    assert.match(await text(page, "#gen-readout"), /^Physical time 0 ms · frame 0 of 0–23 · burn-in · replay frame 1\/13/);
    for (const id of ["gen-map-atmosphere", "gen-map-correction", "gen-map-residual", "gen-psf-uncorrected", "gen-psf-corrected", "gen-scene", "gen-obs-uncorrected", "gen-obs-corrected"]) {
      assert.ok((await canvasInk(page, id)) > 0.3, `${id} is empty`);
    }
    await page.click("#gen-next"); await page.click("#gen-next");
    assert.match(await text(page, "#gen-readout"), /^Physical time 4 ms · frame 4 /);
    assert.match(await text(page, "#gen-note-residual"), /^t = 4 ms/);
    assert.match(await text(page, "#gen-current"), /^Frame 4 \(t = 4 ms\)/);
    await page.check('input[name="gen-obs-mode"][value="running"]');
    assert.match(await text(page, "#gen-obs-ao-caption"), /Unavailable at t = 4 ms: the analysis window starts at frame 8/);
    await page.focus("#gen-seek");
    await page.keyboard.press("End");
    assert.match(await text(page, "#gen-readout"), /frame 23 of 0–23/);
    assert.match(await text(page, "#gen-obs-ao-title"), /running average of 16 samples, frames 8–23/);
    await page.check('input[name="gen-obs-mode"][value="final"]');
    assert.match(await text(page, "#gen-obs-ao-title"), /completed window, frames 8–23 \(16 samples\)/);
    await page.check('input[name="gen-quantity"][value="phase-science"]');
    assert.match(await text(page, "#gen-cbar-opd-labels"), /rad/);
    assert.match(await text(page, "#gen-cbar-opd-note"), /2π × OPD \/ 1\.65 µm, unwrapped/);
    await page.check('input[name="gen-quantity"][value="phase-wfs"]');
    assert.match(await text(page, "#gen-cbar-opd-note"), /not the science wavelength/);
    await page.check('input[name="gen-quantity"][value="opd"]');
    // Replay: keyboard play/pause, loop labelling.
    await page.click("#gen-restart");
    await page.focus("#gen-play"); await page.keyboard.press("Enter");
    assert.equal(await page.getAttribute("#gen-play", "aria-pressed"), "true");
    await sleep(700);
    await page.keyboard.press("Space");
    assert.equal(await page.getAttribute("#gen-play", "aria-pressed"), "false");
    assert.doesNotMatch(await text(page, "#gen-readout"), /replay frame 1\//);
    await page.check("#gen-loop");
    assert.match(await text(page, "#gen-replay-note"), /Loop replay is on: .* replay, not a continuation of the atmosphere/);
    await page.uncheck("#gen-loop");
    // Downloads are the verified bytes of the displayed run.
    const status = await serviceStatus(runs.A);
    const link = await page.$(`a[download="${runs.A}-run.json"]`);
    const size = await page.evaluate(async (href) => (await (await fetch(href)).arrayBuffer()).byteLength, await link.getAttribute("href"));
    assert.equal(size, status.files["run.json"].bytes);
    assert.ok(await page.$(`a[download="${runs.A}-metrics.csv"]`));
    assert.match(await text(page, "#gen-pending"), /equal the displayed run/);
    await setParams(page, { controller_gain: 0.35 });
    assert.match(await text(page, "#gen-pending"), /Pending, not computed: controller_gain 0\.35 \(displayed run: 0\.2\)/);
  });

  await scenario("same-turbulence comparison is labelled paired from digests", async () => {
    await page.click("#gen-compare");
    runs.B = await installedRun(page, runs.A);
    const pairing = await text(page, "#gen-pairing");
    assert.match(pairing, /^Paired comparison: the time grids are identical and all 24 atmosphere samples are byte-identical/);
    assert.match(pairing, /controller_gain/);
    assert.match(pairing, /Calibration identity unchanged/);
    assert.match(await text(page, "#gen-summary-table"), new RegExp(`Reference ${runs.A}`));
    await setParams(page, { guide_ab_magnitude: 8.5, controller_gain: 0.2 });
    await page.click("#gen-compare");
    runs.B2 = await installedRun(page, runs.B);
    assert.match(await text(page, "#gen-pairing"), /^Paired comparison: .*guide_ab_magnitude.* Calibration rebuilt \(guide_ab_magnitude changed\)/);
  });

  await scenario("new realization allocates and records a seed; reproduction is exact", async () => {
    await setParams(page, { guide_ab_magnitude: 7 });
    await page.click("#gen-new");
    runs.C = await installedRun(page, runs.B2);
    const header = await text(page, "#gen-run-id");
    assert.match(header, /new realization allocated by the service/);
    const seed = Number(/seed (\d+)/.exec(header)[1]);
    assert.ok(seed !== 1 && seed !== 2);
    assert.match(await text(page, "#gen-pairing"), /^Not a paired comparison: different random realization/);
    await page.click("#gen-set-reference");
    await page.click("#gen-reproduce");
    runs.D = await installedRun(page, runs.C);
    assert.match(await text(page, "#gen-pairing"), /^Paired comparison: .*identical configuration: an exact replay/);
    assert.ok((await text(page, "#gen-run-id")).includes(`seed ${seed}`));
  });

  await scenario("cancel and failure leave the displayed run in place", async () => {
    await page.route(`${serviceBase}/api/v1/runs`, async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      const body = JSON.parse(route.request().postData());
      body.client_token = page.__fault;
      await route.continue({ postData: JSON.stringify(body) });
    });
    page.__fault = "test-fault:sleep_at:frame3";
    await page.click("#gen-run");
    await waitText(page, "#gen-job-state", (t) => t.startsWith("Computing"));
    const running = (await text(page, "#gen-job-state")).match(/run-\S+/)[0].replace(/[^\w-]$/, "");
    await page.click("#gen-cancel");
    await waitText(page, "#gen-job-state", (t) => t.startsWith("Cancelled"));
    assert.ok((await text(page, "#gen-run-id")).startsWith(runs.D));
    assert.equal(await page.isDisabled("#gen-cancel"), true);
    const cancelled = await serviceStatus(running);
    assert.equal(cancelled.state, "cancelled");
    assert.equal(cancelled.worker.cleanup.process_group_alive_after, false);
    page.__fault = "test-fault:fail_at:built";
    await page.click("#gen-run");
    await waitText(page, "#gen-job-state", (t) => t.startsWith("Failed"));
    assert.match(await text(page, "#gen-job-state"), /injected test fault at built.*displayed run is unchanged/);
    assert.ok((await text(page, "#gen-run-id")).startsWith(runs.D));
    // A newer request supersedes (and cancels) an unfinished one; only the newer result installs.
    page.__fault = "test-fault:sleep_at:frame3";
    await page.click("#gen-run");
    await waitText(page, "#gen-job-state", (t) => t.startsWith("Computing"));
    const superseded = (await text(page, "#gen-job-state")).match(/run-\S+/)[0].replace(/[^\w-]$/, "");
    page.__fault = undefined;
    await page.unroute(`${serviceBase}/api/v1/runs`);
    await setParams(page, { seed: 1 });
    await page.click("#gen-run");
    runs.E = await installedRun(page, runs.D);
    const old = await serviceStatus(superseded);
    assert.equal(old.state, "cancelled");
    assert.match(old.reason, /superseded by a newer request/);
    assert.notEqual(runs.E, superseded);
  });

  await scenario("A→B→A selection ignores a late response", async () => {
    await openRunList(page);
    await page.waitForFunction((ids) => ids.every((id) => document.querySelector(`#gen-runs option[value="${id}"]`)), [runs.A, runs.B]);
    await page.selectOption("#gen-runs", runs.A);
    await page.waitForFunction((id) => document.getElementById("gen-run-id").textContent.startsWith(id), runs.A);
    // B is no longer in the page's small cache, so its load goes to the network and is delayed.
    let delayed = 0;
    await page.route(`${serviceBase}/api/v1/runs/${runs.B}/files/run.json`, async (route) => { delayed += 1; await sleep(1500); await route.continue(); });
    await page.selectOption("#gen-runs", runs.B);
    await page.waitForFunction(() => true, null, { timeout: 300 }).catch(() => {});
    await sleep(300);
    await page.selectOption("#gen-runs", runs.A);
    await sleep(2500);
    assert.equal(delayed, 1, "the B request was not issued");
    assert.ok((await text(page, "#gen-run-id")).startsWith(runs.A));
    assert.match(await text(page, "#gen-readout"), /frame 0 of 0–23/);
    assert.equal(await page.isHidden("#gen-error"), true);
    await page.unroute(`${serviceBase}/api/v1/runs/${runs.B}/files/run.json`);
  });

  await scenario("an interrupted connection is retried and the job is installed", async () => {
    let blocked = true;
    await page.route(new RegExp(`${serviceBase.replace(/[.:/]/g, "\\$&")}/api/v1/runs/run-[^/]+$`), async (route) => {
      if (blocked && route.request().method() === "GET") return route.abort("connectionrefused");
      return route.continue();
    });
    await setParams(page, { controller_gain: 0.25 });
    await page.click("#gen-run");
    await waitText(page, "#gen-job-state", (t) => t.startsWith("Service unreachable"));
    assert.match(await text(page, "#gen-job-state"), /The job keeps running on the service/);
    blocked = false;
    runs.F = await installedRun(page, runs.A);
    await page.unroute(new RegExp(`${serviceBase.replace(/[.:/]/g, "\\$&")}/api/v1/runs/run-[^/]+$`));
  });

  await scenario("coherently rehashed incompatible science metadata is refused", async () => {
    let mutated = null;
    const statusPattern = new RegExp(`${serviceBase.replace(/[.:/]/g, "\\$&")}/api/v1/runs/run-[^/]+$`);
    await page.route(statusPattern, async (route) => {
      const response = await route.fetch();
      const status = await response.json();
      if (status.state === "completed" && status.files) {
        const original = await (await fetch(`${serviceBase}/api/v1/runs/${status.run_id}/files/run.json`)).json();
        original.conventions.science_wavelength_m = 2.2e-6;
        mutated = Buffer.from(JSON.stringify(original));
        status.files["run.json"] = { ...status.files["run.json"], bytes: mutated.length, sha256: crypto.createHash("sha256").update(mutated).digest("hex") };
      }
      await route.fulfill({ response, json: status });
    });
    await page.route(/\/files\/run\.json$/, async (route) => (mutated ? route.fulfill({ body: mutated, contentType: "application/json" }) : route.continue()));
    await setParams(page, { controller_gain: 0.3 });
    await page.click("#gen-run");
    await waitText(page, "#gen-error", (t) => t.includes("science wavelength"));
    assert.match(await text(page, "#gen-error"), /was not installed/);
    assert.match(await text(page, "#gen-job-state"), /refused by this page's checks/);
    assert.ok((await text(page, "#gen-run-id")).startsWith(runs.F));
    await page.unroute(statusPattern);
    await page.unroute(/\/files\/run\.json$/);
  });

  await scenario("disconnect keeps the displayed run and disables computation", async () => {
    await page.click("#gen-disconnect");
    assert.match(await text(page, "#gen-conn-state"), /^Disconnected\. The displayed run stays/);
    for (const id of ["gen-run", "gen-new", "gen-reproduce", "gen-compare"]) assert.equal(await page.isDisabled(`#${id}`), true, id);
    assert.ok((await text(page, "#gen-run-id")).startsWith(runs.F));
    await page.click("#gen-play");
    assert.equal(await page.getAttribute("#gen-play", "aria-pressed"), "true");
    await page.click("#gen-play");
  });
  await context.close();

  await scenario("375 px layout and reduced motion", async () => {
    const { context: small, page: phone } = await newPage(browser, { viewport: { width: 375, height: 800 }, reducedMotion: "reduce" });
    await phone.goto(page_url(`?backend=${encodeURIComponent(serviceBase)}#generate`));
    await connected(phone);
    assert.equal(await phone.inputValue("#gen-speed"), "2");
    await openRunList(phone);
    await phone.waitForFunction((id) => document.querySelector(`#gen-runs option[value="${id}"]`), runs.A);
    await phone.selectOption("#gen-runs", runs.A);
    await phone.waitForFunction((id) => document.getElementById("gen-run-id").textContent.startsWith(id), runs.A);
    const overflow = await phone.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    assert.ok(overflow <= 0, `page-wide horizontal overflow ${overflow}px`);
    await phone.screenshot({ path: `${outDir}/generate-375.png`, fullPage: false });
    await small.close();
  });

  await scenario("same-origin service page and stale-build refusal", async () => {
    const { context: own, page: same } = await newPage(browser);
    await same.goto(`${serviceBase}/ao-explorer/?backend=/`);
    assert.match(await connected(same), new RegExp(`^Connected to ${serviceBase.replace(/[.]/g, "\\.")}`));
    await own.close();
    const { context: stale, page: old } = await newPage(browser);
    await old.route(/\/data\/current\.json$/, async (route) => {
      const response = await route.fetch();
      const entry = await response.json();
      entry.code_build = "0".repeat(16);
      await route.fulfill({ response, json: entry });
    });
    await old.goto(page_url());
    await waitText(old, "#error", (t) => t.includes("reload the page"));
    await stale.close();
  });

  await browser.close();
  assert.deepEqual(pageErrors, []);
  console.log(JSON.stringify({ ok: true, scenarios: results, runs }));
})().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  console.log(JSON.stringify({ ok: false, failed_after: results.map((r) => r.name), error: String(error && error.message), pageErrors }));
  process.exit(1);
});
