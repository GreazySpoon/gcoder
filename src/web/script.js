document.addEventListener('DOMContentLoaded', () => {
    const sessionList = document.getElementById('session-list');
    const newSessionBtn = document.getElementById('new-session-btn');
    const terminalContainer = document.getElementById('terminal');

    const API_URL = 'http://127.0.0.1:8855';
    let currentSessionId = null;
    let commandHistory = [];
    let historyIndex = -1;
    let currentCommand = '';

    // --- Xterm.js Setup ---
    const term = new Terminal({
        cursorBlink: true,
        convertEol: true,
        theme: {
            background: '#1e1e1e',
            foreground: '#d4d4d4',
            cursor: '#d4d4d4',
            selection: 'rgba(255, 255, 255, 0.3)',
        }
    });
    const fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.open(terminalContainer);
    fitAddon.fit();
    window.addEventListener('resize', () => fitAddon.fit());

    const writePrompt = () => {
        currentCommand = '';
        term.write('\r\n\x1b[1;36m(aagent)\x1b[0m > ');
    };

    // --- Core Logic ---

    const fetchSessions = async () => {
        try {
            const response = await fetch(`${API_URL}/sessions`);
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const sessions = await response.json();
            sessionList.innerHTML = '';
            sessions.forEach(session => {
                const li = document.createElement('li');
                li.dataset.sessionId = session.id;
                const sessionIdSpan = document.createElement('span');
                sessionIdSpan.className = 'session-id';
                sessionIdSpan.textContent = `ID: ${session.id.substring(0, 8)}...`;
                const removeBtn = document.createElement('button');
                removeBtn.className = 'remove-session-btn';
                removeBtn.innerHTML = '&times;';
                removeBtn.dataset.sessionId = session.id;
                li.appendChild(sessionIdSpan);
                li.appendChild(removeBtn);
                if (session.id === currentSessionId) {
                    li.classList.add('active');
                }
                sessionList.appendChild(li);
            });
        } catch (error) {
            term.writeln(`\r\n\x1b[31mError fetching sessions: ${error.message}\x1b[0m`);
        }
    };

    const createNewSession = async () => {
        try {
            const response = await fetch(`${API_URL}/sessions`, { method: 'POST' });
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const data = await response.json();
            switchSession(data.session_id, true);
        } catch (error) {
            term.writeln(`\r\n\x1b[31mError creating session: ${error.message}\x1b[0m`);
        }
    };

    const switchSession = (sessionId, isNew = false) => {
        currentSessionId = sessionId;
        term.reset();
        if (isNew) {
            term.writeln(`New session started: ${sessionId}`);
        } else {
            term.writeln(`Switched to session: ${sessionId}`);
        }
        writePrompt();
        fetchSessions();
    };

    const removeSession = async (sessionId) => {
        try {
            const response = await fetch(`${API_URL}/sessions/${sessionId}`, { method: 'DELETE' });
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            if (currentSessionId === sessionId) {
                currentSessionId = null;
                term.reset();
                term.writeln(`Session ${sessionId.substring(0,8)}... removed.`);
                term.writeln('Please select or create a new session.');
            }
            fetchSessions();
        } catch (error) {
            term.writeln(`\r\n\x1b[31mError removing session: ${error.message}\x1b[0m`);
        }
    };
    
    const renderTaskDashboard = (state) => {
        let output = '\r\n\x1b[1;32m📋 Plan\x1b[0m\r\n';
        if (state.plan && state.plan.plan) {
            state.plan.plan.forEach((step, index) => {
                const status = state.step_statuses[index] || 'pending';
                if (status === 'in_progress') {
                    output += `\x1b[33m🔄 ${step}\x1b[0m\r\n`;
                } else if (status === 'success') {
                    output += `\x1b[32m✅ ${step}\x1b[0m\r\n`;
                } else {
                    output += `\x1b[90m⚪ ${step}\x1b[0m\r\n`;
                }
            });
        }
        if(state.latest_verdict) {
            output += `\r\n\x1b[1;35m🕵️ Verdict:\x1b[0m ${state.latest_verdict}\r\n`;
        }
        // Clear the screen and render
        term.write('\x1b[2J\x1b[H'); // ANSI escape codes to clear screen
        term.writeln(output);
    };

    const dispatchCommand = (prompt) => {
        if (!currentSessionId) {
            term.writeln(`\r\n\x1b[31mPlease create or select a session first.\x1b[0m`);
            writePrompt();
            return;
        }

        const eventSource = new EventSource(`${API_URL}/sessions/${currentSessionId}/dispatch?prompt=${encodeURIComponent(prompt)}`);
        
        let finalResponseStarted = false;
        let streamClosedGracefully = false;

        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                const eventType = data.event;

                if (eventType === 'error') {
                    term.writeln(`\r\n\x1b[1;31mError: ${data.data}\x1b[0m`);
                    streamClosedGracefully = true;
                    eventSource.close();
                    writePrompt();
                    return;
                }

                if (eventType === 'RunCompleted' || eventType === 'WorkflowCompleted') {
                    streamClosedGracefully = true;
                }

                if (eventType === 'RunResponseContent' && data.content) {
                    if (!finalResponseStarted) {
                        term.writeln('');
                        finalResponseStarted = true;
                    }
                    term.write(data.content);
                } else if (eventType === 'ToolCallStarted' && data.tool) {
                    term.writeln(`\r\n\x1b[33m🤔 Executing Tool: ${data.tool.tool_name}(${JSON.stringify(data.tool.tool_args)})\x1b[0m`);
                } else if (eventType === 'ToolCallCompleted' && data.tool) {
                    const result = data.tool.result || '';
                    const resultLines = result.split('\n').map(line => `\t${line}`).join('\r\n');
                    term.writeln(`\x1b[32m✅ Tool Succeeded:\x1b[0m\r\n${resultLines}`);
                }
                // --- @task UI Events ---
                else if (eventType === 'ui_update' && data.state) {
                    renderTaskDashboard(data.state);
                }
                else if (eventType === 'final_summary' && data.data) {
                    term.writeln(`\r\n\x1b[1;32m✅ Task Summary:\x1b[0m\r\n${data.data}`);
                }

            } catch (e) {
                console.warn("Could not parse JSON chunk:", event.data, e);
            }
        };

        eventSource.onerror = (error) => {
            eventSource.close();
            // THE FIX IS HERE: Only show the error if the stream did not close gracefully.
            if (!streamClosedGracefully) {
                term.writeln(`\r\n\x1b[31mStream Error: Connection to server lost.\x1b[0m`);
                console.error('EventSource failed:', error);
            }
            writePrompt();
        };
    };

    // --- Xterm.js Input Handling ---
    term.onKey(({ key, domEvent }) => {
        const printable = !domEvent.altKey && !domEvent.ctrlKey && !domEvent.metaKey;

        if (domEvent.keyCode === 13) { // Enter
            if (currentCommand.trim()) {
                commandHistory.push(currentCommand);
                historyIndex = commandHistory.length;
                term.write('\r\n');
                dispatchCommand(currentCommand);
                currentCommand = '';
            } else {
                writePrompt();
            }
        } else if (domEvent.keyCode === 8) { // Backspace
            if (currentCommand.length > 0) {
                term.write('\b \b');
                currentCommand = currentCommand.slice(0, -1);
            }
        } else if (printable) {
            term.write(key);
            currentCommand += key;
        }
    });

    // --- Event Listeners ---
    newSessionBtn.addEventListener('click', createNewSession);
    sessionList.addEventListener('click', (e) => {
        const target = e.target;
        if (target.classList.contains('remove-session-btn')) {
            e.stopPropagation();
            removeSession(target.dataset.sessionId);
        } else if (target.closest('li')) {
            switchSession(target.closest('li').dataset.sessionId);
        }
    });

    // --- Initialization ---
    term.writeln('Welcome to aagent! Initializing...');
    fetchSessions();
    writePrompt();
});