"""Apply Pi's explicit MCP scope policy to the pinned client."""

from hashlib import sha256
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile


CLIENT_DIR = Path('node_modules/@earendil-works/pi-coding-agent/dist')

POLICY = '''function scopeList(value) {
    return typeof value === "string" ? value.split(/\\s+/).filter(Boolean) : [];
}

function restrictOAuthStore(store, allowed) {
    if (!allowed.length)
        return store;
    const allows = (tokens) => {
        const granted = scopeList(tokens?.scope);
        return granted.length > 0 && granted.every((scope) => allowed.includes(scope));
    };
    return {
        ...store,
        load: async () => {
            const state = await store.load();
            if (state?.tokens && !allows(state.tokens)) {
                const safe = { ...state };
                delete safe.tokens;
                delete safe.tokensExpireAt;
                return safe;
            }
            return state;
        },
        save: (state) => {
            if (state.tokens && !allows(state.tokens))
                throw new Error("MCP OAuth grant exceeds or does not declare the configured scope");
            return store.save(state);
        },
    };
}

'''

# Pi has both a bundled launcher and importable modules. Check every pinned preimage first.
PATCHES = {
    'extensions/mcp/runtime.js': (
        '1ed03790749c1c494f6ff3891652a4ad895cb25bf2ad4ed61202837c5e3055fb',
        ((
            '                settings: () => this.oauthSettings(),\n',
            '                settings: () => this.oauthSettings(),\n'
            '                scope: this.entry.config.oauth?.scope,\n',
        ),),
    ),
    'extensions/mcp/oauth.js': (
        '60b5c1fde162e01639a712c0f160c7833380dd9c32fc9983aeac688d3890e0e5',
        (
            ('/** pi-mcp\'s `createMcpAuthProvider` with pi\'s client identity. */',
             POLICY + '/** pi-mcp\'s `createMcpAuthProvider` with pi\'s client identity. */'),
            ('    return createAuthProvider({ ...options, ...PI_CLIENT, settings: () => piSettings(options.settings()) });',
             '    const store = restrictOAuthStore(options.store, scopeList(options.scope));\n'
             '    return createAuthProvider({ ...options, store, ...PI_CLIENT, settings: () => piSettings(options.settings()) });'),
            ('    const { serverUrl, store, challenge, prompt, signal } = options;\n'
             '    const settings = piSettings(options.settings);',
             '    const { serverUrl, prompt, signal } = options;\n'
             '    const settings = piSettings(options.settings);\n'
             '    const allowed = scopeList(settings.scope);\n'
             '    const store = restrictOAuthStore(options.store, allowed);\n'
             '    const challenge = allowed.length && options.challenge\n'
             '        ? { ...options.challenge, scope: undefined }\n'
             '        : options.challenge;'),
        ),
    ),
    'bundle/chunks/chunk-FMPAMX2W.js': (
        '4378273f622a17f18ed6db86b71204186109b39afeaee00e34bfa5684bdb21c0',
        (
            ('function createMcpAuthProvider2(options){return createMcpAuthProvider({...options,...PI_CLIENT,',
             POLICY + 'function createMcpAuthProvider2(options){'
             'const store=restrictOAuthStore(options.store,scopeList(options.scope));'
             'return createMcpAuthProvider({...options,store,...PI_CLIENT,'),
            ('let{serverUrl,store,challenge,prompt,signal}=options,settings=piSettings(options.settings),'
             '{callback,redirectUrl}=await listenForLoopbackSignIn',
             'let{serverUrl,prompt,signal}=options,settings=piSettings(options.settings),'
             'allowed=scopeList(settings.scope),store=restrictOAuthStore(options.store,allowed),'
             'challenge=allowed.length&&options.challenge?{...options.challenge,scope:void 0}:options.challenge,'
             '{callback,redirectUrl}=await listenForLoopbackSignIn'),
            ('settings:()=>this.oauthSettings(),onChallenge:',
             'settings:()=>this.oauthSettings(),scope:this.entry.config.oauth?.scope,onChallenge:'),
        ),
    ),
}


def replacement(path, expected, edits):
    original = path.read_bytes()
    source = original.decode('utf-8')
    if sha256(original).hexdigest() != expected:
        for before, after in reversed(edits):
            if source.count(after) != 1:
                break
            source = source.replace(after, before)
        else:
            if sha256(source.encode('utf-8')).hexdigest() == expected:
                return None
        raise SystemExit(f'Unexpected MCP dependency bytes in {path.name}. Reinstall the pinned dependencies.')
    for before, after in edits:
        if source.count(before) != 1:
            raise SystemExit(f'Unexpected MCP scope patch target in {path.name}.')
        source = source.replace(before, after)
    return source.encode('utf-8')


def main():
    directory = Path(sys.argv[1]) / CLIENT_DIR
    changed = [(directory / name, replacement(directory / name, *patch)) for name, patch in PATCHES.items()]
    for path, data in changed:
        if data is None:
            continue
        with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            temporary.write(data)
        staged = Path(temporary.name)
        try:
            staged.replace(path)
        finally:
            staged.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
