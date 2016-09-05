(function() {
    var httpsEnabled = window.location.protocol == "https:";
    var args = window.location.search;
    var url = (httpsEnabled ? 'wss://' : 'ws://') + window.location.host + window.location.pathname + '/ws';
    var autoReconnect = -1;

    var openWs = function() {
        var ws = new WebSocket(url);
        var term;
        var pingTimer;

        ws.onopen = function(event) {
            sendMessage(ws, 'init', JSON.stringify({ Arguments: args, AuthToken: ""}));
            pingTimer = setInterval(sendPing, 30 * 1000, ws);

            hterm.defaultStorage = new lib.Storage.Local();
            hterm.defaultStorage.clear();

            term = new hterm.Terminal();
            term.getPrefs().set("send-encoding", "raw");
            term.onTerminalReady = function() {
                var io = term.io.push();
                io.onVTKeystroke = function(str) {
                    sendMessage(ws, "input", str);
                };
                io.sendString = io.onVTKeystroke;

                // when user resize browser, send columns and rows to server.
                io.onTerminalResize = function(columns, rows) {
                    sendMessage(ws, "resize", JSON.stringify({columns: columns, rows: rows}))
                };
                term.installKeyboard();
            };
            term.decorate(document.getElementById("terminal"));
        };

        ws.onmessage = function(event) {
            data = JSON.parse(event.data);
            switch(data.type) {
                case 'output':
                    // decode message and convert to utf-8
                    term.io.writeUTF8(window.atob(data.content));
                    break;
                case 'pong':
                    // pong
                    break;
                case 'set-title':
                    term.setWindowTitle(data.content);
                    break;
                case 'set-preferences':
                    var preferences = JSON.parse(data.content);
                    Object.keys(preferences).forEach(function(key) {
                        console.log("Setting " + key + ": " +  preferences[key]);
                        term.getPrefs().set(key, preferences[key]);
                    });
                    break;
                case 'set-autoreconnect':
                    autoReconnect = JSON.parse(data.content);
                    console.log("Enabling reconnect: " + autoReconnect + " seconds")
                    break;
                case 'error':
                    term.io.writeUTF8(window.atob(data.content));
                    break;
                default:
                    // unidentified message
                    term.io.writeUTF8("Invalid message: " + event.data);
            }
        };

        ws.onclose = function(event) {
            if (term) {
                term.uninstallKeyboard();
                term.io.showOverlay("Connection Closed", null);
            }
            clearInterval(pingTimer);
            if (autoReconnect > 0) {
                setTimeout(openWs, autoReconnect * 1000);
            }
        };
    };

    var sendMessage = function(ws, type, content) {
        message = JSON.stringify({
            type: type,
            content: content
        })
        if(ws.readyState != 3) {
            ws.send(message)
        }
    };

    var sendPing = function(ws) {
        sendMessage(ws, "ping", "1");
    }

    openWs();
})()
