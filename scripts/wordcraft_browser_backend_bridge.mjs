// Confined JSON-lines bridge used only by the disposable G4 end-to-end proof.
// It keeps one real Chromium/WASM canvas alive across backend commit and Undo.
import {createHash} from 'node:crypto';
import {readFile, realpath} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {buildAssets, browserEnvironment, browserExecutablePath, QA_PIN,
  serveAssets, verifyPlaywright} from './wordcraft_browser_qa.mjs';

const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const fail = message => { throw new Error(message); };

function argumentsOf(values) {
  const names = new Set(['bundle', 'manifest-sha256', 'playwright', 'producer-commit']);
  if (values.length !== names.size * 2) fail('closed arguments');
  const result = {};
  for (let index = 0; index < values.length; index += 2) {
    const name = values[index].slice(2);
    if (!values[index].startsWith('--') || !names.has(name) || Object.hasOwn(result, name)) fail('closed arguments');
    result[name] = values[index + 1];
  }
  if (!/^[0-9a-f]{64}$/.test(result['manifest-sha256'])
      || !/^[0-9a-f]{40}$/.test(result['producer-commit'])) fail('closed pins');
  return result;
}

const emit = value => process.stdout.write(JSON.stringify(value) + '\n');

async function main() {
  const config = argumentsOf(process.argv.slice(2));
  config.bundle = await realpath(config.bundle);
  config.playwright = await realpath(config.playwright);
  const built = await buildAssets(config);
  const pkg = await verifyPlaywright(config.playwright);
  const executablePath = await realpath(browserExecutablePath());
  const executableSha256 = digest(await readFile(executablePath));
  const server = await serveAssets(built.assets);
  const {chromium} = await import(pathToFileURL(pkg.entry).href);
  let browser, context, page, denied = 0, pageErrors = 0, consoleErrors = 0;
  try {
    browser = await chromium.launch({headless: true, timeout: 45_000,
      env: browserEnvironment(), executablePath,
      args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
        '--disable-dev-shm-usage', '--disable-background-networking', '--disable-component-update',
        '--disable-sync', '--no-first-run']});
    if (browser.version() !== QA_PIN.chromiumVersion) fail('browser version');
    context = await browser.newContext({viewport: {width: 1366, height: 900}, locale: 'pt-BR',
      timezoneId: 'UTC', acceptDownloads: false, serviceWorkers: 'block'});
    context.setDefaultTimeout(45_000);
    await context.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.origin === server.origin && built.assets.has(url.pathname) && !url.search) return route.continue();
      denied++; return route.abort();
    });
    page = await context.newPage();
    page.on('pageerror', () => { pageErrors++; });
    page.on('console', message => { if (message.type() === 'error') consoleErrors++; });
    await page.goto(server.origin + '/', {waitUntil: 'load'});
    await page.waitForFunction(() => Boolean(window.qa));
    emit({event: 'ready', browser_version: browser.version(), browser_executable_sha256: executableSha256,
      engine_manifest_sha256: config['manifest-sha256']});

    const readline = await import('node:readline');
    const lines = readline.createInterface({input: process.stdin, crlfDelay: Infinity, terminal: false});
    for await (const line of lines) {
      const command = JSON.parse(line);
      let value;
      if (command.action === 'open') {
        value = await page.evaluate(input => window.qa.open(input.content_base64, input.content_hash), command);
      } else if (command.action === 'probe') {
        value = await page.evaluate(() => window.qa.probe());
      } else if (command.action === 'apply') {
        value = await page.evaluate(input => window.qa.applyPersistedPatch(
          input.operation_id, input.revision, input.target_hash, input.plan), command);
      } else if (command.action === 'ack') {
        value = await page.evaluate(input => window.qa.acceptPersistedPatch(input.ack), command);
      } else if (command.action === 'freeze_approval') {
        value = await page.evaluate(() => window.qa.freezeForApproval());
      } else if (command.action === 'verify_approved_frozen') {
        value = await page.evaluate(input => window.qa.verifyApprovedFrozen(input.expected), command);
      } else if (command.action === 'patch_ack_undo') {
        value = await page.evaluate(input => window.qa.acceptPersistedPatchAndUndo(input.ack), command);
      } else if (command.action === 'undo_ack') {
        value = await page.evaluate(input => window.qa.acceptPersistedUndo(input.ack), command);
      } else if (command.action === 'close') {
        value = {denied_requests: denied, page_errors: pageErrors, console_errors: consoleErrors};
        emit({event: 'result', action: command.action, value});
        break;
      } else fail('closed command');
      emit({event: 'result', action: command.action, value});
    }
    lines.close();
    process.stdin.destroy();
  } finally {
    await page?.evaluate(() => window.qa?.close()).catch(() => {});
    await page?.close().catch(() => {});
    await context?.close().catch(() => {});
    await browser?.close().catch(() => {});
    await server.close().catch(() => {});
  }
}

main().catch(error => {
  const allowed = new Set(['PATCH_ACK_INPUT', 'PATCH_ACK_REJECTED', 'UNDO_COMMAND_REFUSED',
    'UNDO_DID_NOT_CHANGE', 'UNDO_CHECKPOINT_INVALID']);
  const message = String(error?.message ?? '');
  const code = [...allowed].find(item => message.includes(item));
  emit({event: 'failure', code: code ?? 'CLOSED_BROWSER_BRIDGE_FAILURE'});
  process.stdin.destroy(); process.exitCode = 1;
});
