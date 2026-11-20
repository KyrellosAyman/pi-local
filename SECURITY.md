# Security and local data

The supplied workflow uses a single authenticated model endpoint on 127.0.0.1. Setup generates a fresh local credential and stores it under the ignored `.local/` directory. The public repository contains no configured cloud credentials. GitHub, Hugging Face, PyPI and npm are used for public inbound downloads when requested. Asset setup checks the pinned byte counts and SHA-256 values before extracting the native packages.

The Windows launcher rejects a foreign model listener and relies on the bundled loopback settings. Webpage tools and outside skill directories are disabled in a fresh release profile. Browser or desktop integrations require a separately supplied driver. Local state and the default workspace are separate from the tracked release files.

Pi can execute local tools with the permissions of the Windows user. Use a scratch workspace for untrusted files and keep the model endpoint on loopback. The Windows desktop process is not an OS sandbox. Avoid granting access to credentials, broad home directories, or private browser data through custom tools. Review any shell, MCP or browser integration before enabling it.

Report suspected credential disclosure or a security defect through [GitHub private vulnerability reporting](https://github.com/KyrellosAyman/pi-local/security/advisories/new). Include the release and affected surface without posting credentials, raw chats or signed-in browser data in a public issue.
