# Samurai AI System Configuration

> **Legacy design document.** `samurai-ai` exists and stores provider
> credentials, but it targets local Ollama only: cloud chat, speech input and
> speech output described below are not implemented, ctransformors is not used,
> and Ollama is not baked into the live ISO. See
> [`../docs/ai-system.md`](../docs/ai-system.md) for the implemented behaviour.

## 4.1 Local AI Runtime

### Engine Selection
- **Primary**: llama.cpp - lightweight, CPU/GPU compatible, supports many model formats
- **Secondary**: Ollama - user-friendly wrapper around llama.cpp with model management
- **Fallback**: ctransformors - Python library for fast inference

### Model Discovery and Installation
```bash
# List available models
samurai-ai list-models

# Install a model
samurai-ai install-model <model-id>

# Delete a model
samurai-ai delete-model <model-name>
```

### Hardware Detection
```bash
# Check GPU availability
samurai-ai gpu-info

# CPU capability check
samurai-ai cpu-info

# Memory budget
samurai-ai memory-budget
```

### Model Configuration
```bash
# Set default model
samurai-ai set-default <model-id>

# Check model compatibility
samurai-ai check-compatibility <model-id>

# View inference status
samurai-ai status
```

### Resource Controls
- Context-length limits based on available RAM
- Memory-budget controls to prevent desktop unresponsiveness
- Automatic inference pause when system load is high

## 4.2 Samurai AI Assistant

### Interface
- **Desktop widget**: KDE Plasma applet
- **Keyboard shortcut**: `Ctrl`+`Space` to activate
- **System tray** indicator for status

### Features
- Chat interface with conversation history
- User-controlled retention (configurable TTL)
- Code explanation and debugging assistance
- Project planning and implementation assistance
- File summarization and document analysis
- Terminal command explanations
- System troubleshooting guidance
- Developer documentation assistance

### Optional Features
- Speech input (via Whisper or similar)
- Speech output (via eSpeak or similar)
- Cloud model integrations (OpenAI, Anthropic, etc.)

## 4.3 Intelligent Model Router

### Task Categories
- **Coding**: Model selection for programming tasks
- **Reasoning**: For logical analysis and problem-solving
- **Summarization**: Document and meeting summary generation
- **Lightweight chat**: Casual conversation
- **Document analysis**: Text extraction and analysis
- **Local offline**: Models that run entirely on-device

### Selection Criteria
1. Available hardware (CPU/GPU, VRAM, system RAM)
2. Context-window requirements vs. available memory
3. Measured quality benchmarks (when available)
4. Memory and latency constraints
5. Estimated cost (for cloud providers)
6. Privacy requirements (local vs. cloud)
7. Provider availability
8. User-selected preferences

### Router Output
```
Recommended model: gemma-3-12b-it (local)
Task: code explanation
Estimated latency: 2.3s per 100 tokens
Will stay on-device: Yes
Cost: $0.00
```

## 4.4 AI-Assisted System Operations

### Permissioned Execution
All AI-proposed actions require explicit user confirmation for:
- Package installation/removal
- Privileged commands (sudo, etc.)
- Disk changes
- Firewall modifications
- Credential access
- Security-sensitive changes

### Supported Tasks
- Installing approved packages
- Creating development environments
- Generating project scaffolding
- Running tests
- Diagnosing logs
- Configuring development tools
- Managing model installations
- Explaining system configuration changes

### Safety Controls
- Never silently upload files, source code, logs, credentials, or system info to cloud
- Clear disclosure when request will leave device or incur charges
- User override always available

## 4.5 Cloud and Offline Modes

### Local Mode
- Uses locally available models
- No cloud API credentials required
- Subject to model and hardware limitations
- Preferred for privacy-sensitive work

### Cloud Mode
- Users configure supported providers with their own credentials
- Supported providers: OpenAI, Anthropic, Google, local Ollama instances
- Credentials stored in OS credential store (Kwallet/SecretService)
- Clearly disclose external data transmission

### Credential Storage
```bash
# Store API key securely
samurai-ai credentials set <provider> <key>

# Retrieve API key
samurai-ai credentials get <provider>

# Remove stored credential
samurai-ai credentials remove <provider>
```
