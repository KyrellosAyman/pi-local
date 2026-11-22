import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { promisify } from 'node:util';

const client = resolve(process.argv[2]);
const dist = join(client, 'node_modules/@earendil-works/pi-coding-agent/dist');
const implementation = process.argv.includes('--modules')
    ? 'extensions/mcp/cli.js' : 'bundle/chunks/cli-7RHMDOHL.js';
const { runMcpCommand } = await import(pathToFileURL(join(dist, implementation)));
const root = await mkdtemp(join(tmpdir(), 'pi-scope-fixture-'));
const cases = [];
const access = (number) => `local-fixture-access-${number}`;
let scenario;
let origin;
const send = (response, status, payload) => {
    response.writeHead(status, payload === undefined ? {} : { 'content-type': 'application/json' });
    response.end(payload === undefined ? undefined : JSON.stringify(payload));
};
const server = createServer(async (request, response) => {
    try {
        const url = new URL(request.url, origin);
        const resource = `${origin}/mcp`;
        const discovery = `${origin}/.well-known/oauth-protected-resource/mcp`;
        if (url.href === discovery) {
            return send(response, 200, { resource, authorization_servers: [origin], scopes_supported: ['read'] });
        }
        if (url.pathname === '/.well-known/oauth-authorization-server') {
            return send(response, 200, { issuer: origin, authorization_endpoint: `${origin}/authorize`,
                token_endpoint: `${origin}/token`, response_types_supported: ['code'],
                code_challenge_methods_supported: ['S256'], token_endpoint_auth_methods_supported: ['none'] });
        }
        let body = '';
        if (request.method === 'POST') {
            for await (const part of request) body += part;
        }
        if (url.pathname === '/token') {
            const form = new URLSearchParams(body);
            assert.equal(form.get('client_id'), 'loopback-fixture-client');
            assert.equal(form.get('resource'), resource);
            const grant = form.get('grant_type');
            scenario.grants.push(grant);
            if (grant === 'authorization_code') {
                assert.equal(form.get('code'), 'local-fixture-code');
                const verifier = createHash('sha256').update(form.get('code_verifier')).digest('base64url');
                assert.ok(verifier === scenario.challenge, 'PKCE verifier mismatch');
            } else {
                assert.equal(grant, 'refresh_token');
                assert.ok(form.get('refresh_token') === 'local-fixture-refresh', 'Unexpected refresh token');
            }
            scenario.tokenCount += 1;
            const scope = grant === 'authorization_code' ? scenario.codeScope : scenario.refreshScope;
            return send(response, 200, { access_token: access(scenario.tokenCount),
                refresh_token: 'local-fixture-refresh', token_type: 'Bearer', expires_in: 3600, scope });
        }
        assert.equal(url.pathname, '/mcp');
        const bearer = request.headers.authorization;
        if (bearer) scenario.sent.push(bearer);
        if (!scenario.tokenCount || bearer !== `Bearer ${access(scenario.tokenCount)}` || scenario.expired === scenario.tokenCount) {
            response.setHeader('www-authenticate', `Bearer resource_metadata="${discovery}", scope="read write"`);
            return send(response, 401);
        }
        if (request.method !== 'POST') return send(response, 405);
        const message = JSON.parse(body);
        if (message.id === undefined) return send(response, 202);
        const results = {
            initialize: { protocolVersion: message.params?.protocolVersion, capabilities: { tools: {} },
                serverInfo: { name: 'scope-fixture', version: '1' } },
            'tools/list': { tools: [{ name: 'read_fixture', description: 'Read the synthetic fixture',
                inputSchema: { type: 'object' } }] },
        };
        assert.ok(results[message.method]);
        return send(response, 200, { jsonrpc: '2.0', id: message.id, result: results[message.method] });
    } catch {
        scenario.errors += 1;
        send(response, 500);
    }
});

async function prepare(name, scope, tokenOptions) {
    const profile = join(root, name);
    await mkdir(profile);
    await writeFile(join(profile, 'mcp.json'), JSON.stringify({ mcpServers: { scope_fixture: {
        url: `${origin}/mcp`, oauth: { clientId: 'loopback-fixture-client', scope },
    } } }));
    scenario = { grants: [], sent: [], errors: 0, tokenCount: 0, ...tokenOptions };
    return profile;
}

async function login(profile, expectedScope) {
    let approval;
    let problem;
    process.env.PI_CODING_AGENT_DIR = profile;
    const exit = await runMcpCommand(['login', 'scope_fixture', '--timeout', '3'], {
        cwd: root, agentDir: profile, log() {}, error() {}, openUrl(address) {
            approval = (async () => {
                const url = new URL(address);
                assert.equal(url.origin, origin);
                assert.equal(url.pathname, '/authorize');
                assert.equal(url.searchParams.get('scope'), expectedScope);
                assert.equal(url.searchParams.get('resource'), `${origin}/mcp`);
                assert.equal(url.searchParams.get('code_challenge_method'), 'S256');
                scenario.challenge = url.searchParams.get('code_challenge');
                assert.match(scenario.challenge, /^[a-zA-Z0-9_-]{43}$/);
                const redirect = new URL(url.searchParams.get('redirect_uri'));
                assert.match(redirect.href, /^http:\/\/127\.0\.0\.1:\d+\/callback$/);
                redirect.searchParams.set('code', 'local-fixture-code');
                redirect.searchParams.set('state', url.searchParams.get('state'));
                const response = await fetch(redirect);
                assert.equal(response.status, 200);
            })().catch(error => { problem = error; });
        },
    });
    await approval;
    if (problem) throw problem;
    assert.ok(approval, 'Pi did not start OAuth sign-in');
    assert.equal(scenario.errors, 0);
    return exit;
}

async function authState(profile) {
    const authFile = join(profile, 'mcp-auth.json');
    const states = JSON.parse(await readFile(authFile, 'utf8'));
    const state = Object.values(states)[0];
    return { state, states, authFile };
}

async function list(profile) {
    const { stdout } = await promisify(execFile)(process.execPath,
        [join(dist, 'bundle/cli.js'), 'mcp', 'list', '--json'], {
            cwd: root, env: { ...process.env, PI_CODING_AGENT_DIR: profile }, timeout: 7000, windowsHide: true,
        });
    return JSON.parse(stdout);
}

try {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    origin = `http://127.0.0.1:${server.address().port}`;
    const read = await prepare('read', 'read');
    if (process.argv.includes('--preimage')) {
        assert.equal(await login(read, 'read write'), 0);
        console.log(JSON.stringify({ preimageReproduced: true }));
    } else {
        assert.equal(await login(read, 'read'), 0);
        assert.equal((await authState(read)).state.tokens.scope, 'read');
        scenario.expired = scenario.tokenCount;
        const report = await list(read);
        assert.ok(JSON.stringify(report).includes('read_fixture'));
        assert.deepEqual(scenario.grants, ['authorization_code', 'refresh_token']);
        assert.equal((await authState(read)).state.tokens.scope, 'read');
        cases.push('configured read, omitted scope, fresh CLI refresh and authenticated catalog');

        const broad = await prepare('broad', 'read', { codeScope: 'read write' });
        assert.equal(await login(broad, 'read'), 1);
        assert.equal((await authState(broad)).state.tokens, undefined);
        assert.equal(scenario.sent.length, 0);
        cases.push('overbroad token response refused before use or persistence');

        const refresh = await prepare('refresh', 'read', { refreshScope: 'read write' });
        assert.equal(await login(refresh, 'read'), 0);
        scenario.expired = scenario.tokenCount;
        await assert.rejects(() => list(refresh));
        assert.deepEqual(scenario.grants, ['authorization_code', 'refresh_token']);
        assert.ok(!scenario.sent.includes(`Bearer ${access(2)}`));
        assert.equal((await authState(refresh)).state.tokens.scope, 'read');
        cases.push('overbroad refresh refused before use or persistence');

        const { state, states, authFile } = await authState(read);
        scenario = { grants: [], sent: [], errors: 0, tokenCount: 0 };
        for (const previous of ['read write', undefined]) {
            state.tokens.scope = previous;
            await writeFile(authFile, JSON.stringify(states));
            await assert.rejects(() => list(read));
        }
        assert.deepEqual(scenario.grants, []);
        assert.deepEqual(scenario.sent, []);
        assert.equal(await login(read, 'read'), 0);
        cases.push('legacy broad or unknown grant withheld and normal sign-in succeeds');

        for (const scope of ['read write', undefined]) {
            const profile = await prepare(scope ? 'explicit-write' : 'discovered', scope);
            assert.equal(await login(profile, 'read write'), 0);
            assert.equal((await authState(profile)).state.tokens.scope, 'read write');
        }
        cases.push('explicit write and unconfigured discovery retain their behavior');
        console.log(JSON.stringify({ passed: cases }));
    }
} finally {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
    await rm(root, { recursive: true, force: true });
}
