# Third-party assets

The bundled `native-qwen/chat-template.jinja` comes from the `tokenizer.chat_template` field in the [pinned JonathanColetti GGUF](https://huggingface.co/JonathanColetti/Qwen3.8-27B-Uncensored-GGUF/tree/45d0fc0ad6cfcf9eeee6008ddaea925536409b18), published under the [Apache License 2.0](licenses/Apache-2.0.txt). Pi Local added a mapping for the desktop client's reasoning effort names. The embedded original remains in the downloaded weights.

Setup obtains llama.cpp and CUDA libraries from their upstream release and obtains the weights from their publisher. Those assets retain their upstream terms. The Node and Python packages remain under their respective package licenses.

Setup also obtains [ripgrep 15.2.0](https://github.com/BurntSushi/ripgrep/releases/tag/15.2.0) and [fd 10.5.2](https://github.com/sharkdp/fd/releases/tag/v10.5.2) from their upstream releases. Each verified archive is extracted with its original license files. [ripgrep license](https://github.com/BurntSushi/ripgrep/blob/15.2.0/COPYING) [fd MIT license](https://github.com/sharkdp/fd/blob/v10.5.2/LICENSE-MIT) [fd Apache license](https://github.com/sharkdp/fd/blob/v10.5.2/LICENSE-APACHE)

Optional audio analysis uses separately downloaded upstream assets. The [NeMo-Speech.cpp v0.3.0 archive](https://github.com/NVIDIA/NeMo-Speech.cpp/releases/tag/v0.3.0) includes its own license and third-party notices. NVIDIA publishes the [Parakeet Q8 weights](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3/blob/541d1f99c6b0c3cd0b11a95167540bb8edefd82b/parakeet-tdt-0.6b-v3.q8_0.gguf) under CC BY 4.0. Audio Magic provides the [YAMNet ONNX conversion](https://huggingface.co/audiomagic/yamnet-onnx/tree/f25b741c2f0bdc6d7e6db24b5fddda23347dbafd) under Apache 2.0.
