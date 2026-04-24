// if you don't want the last move of each player side to be "highlighted", set the variable highlight_move to
// HIGHLIGHT_OFF
const HIGHLIGHT_OFF = 0;
const HIGHLIGHT_ON = 1;
var highlight_move = HIGHLIGHT_ON;

const NAG_NULL = 0;
const NAG_GOOD_MOVE = 1;
//"""A good move. Can also be indicated by ``!`` in PGN notation."""
const NAG_MISTAKE = 2;
//"""A mistake. Can also be indicated by ``?`` in PGN notation."""
const NAG_BRILLIANT_MOVE = 3;
//"""A brilliant move. Can also be indicated by ``!!`` in PGN notation."""
const NAG_BLUNDER = 4;
//"""A blunder. Can also be indicated by ``??`` in PGN notation."""
const NAG_SPECULATIVE_MOVE = 5;
//"""A speculative move. Can also be indicated by ``!?`` in PGN notation."""
const NAG_DUBIOUS_MOVE = 6;
//"""A dubious move. Can also be indicated by ``?!`` in PGN notation."""

var simpleNags = {
    '1': '!',
    '2': '?',
    '3': '!!',
    '4': '??',
    '5': '!?',
    '6': '?!',
    '7': '&#9633',
    '8': '&#9632',
    '11': '=',
    '13': '&infin;',
    '14': '&#10866',
    '15': '&#10865',
    '16': '&plusmn;',
    '17': '&#8723',
    '18': '&#43; &minus;',
    '19': '&minus; &#43;',
    '36': '&rarr;',
    '142': '&#8979',
    '146': 'N'
};
var webAudioMode = "off";
if (typeof window !== "undefined" && window.picoWebConfig) {
    if (window.picoWebConfig.webAudioBackend === true) {
        webAudioMode = "backend";
    } else if (window.picoWebConfig.webSpeech !== false) {
        webAudioMode = "tts";
    }
}

function isLocalWebClient() {
    const hostname = String(location.hostname || '').toLowerCase();
    return hostname === '127.0.0.1' || hostname === 'localhost' || hostname === '::1';
}

function updateWebAudioMuteButtonVisibility() {
    const muteButton = $('#btn-mute');
    if (isLocalWebClient() || webAudioMode === "off") {
        muteButton.hide();
    } else {
        muteButton.addClass('is-muted is-visible').show();
    }
}

function isBrowserSpeechAllowed() {
    if (window.picoWebConfig && Object.prototype.hasOwnProperty.call(window.picoWebConfig, 'webSpeechFallback')) {
        return window.picoWebConfig.webSpeechFallback !== false;
    }
    return !(window.picoWebConfig && window.picoWebConfig.webSpeech === false);
}

function applyWebAudioBackendRemote(enabled) {
    window.picoWebConfig = window.picoWebConfig || {};
    window.picoWebConfig.webAudioBackend = Boolean(enabled) && !isLocalWebClient();

    if (window.picoWebConfig.webAudioBackend === true) {
        webAudioMode = "backend";
    } else if (isBrowserSpeechAllowed()) {
        webAudioMode = "tts";
    } else {
        webAudioMode = "off";
    }

    if (webAudioMode !== "backend") {
        stopBackendAudioPlayback();
    }
    setSpeechMuted(true);
    updateWebAudioMuteButtonVisibility();

    if (window.updatePicoSystemAudioState) {
        window.updatePicoSystemAudioState();
    }
}

// 3check variant support
var currentVariant = "chess";

function updateCheckCounters(variant, checks) {
    var checkCounters = document.getElementById('checkCounters');
    if (!checkCounters) return;

    // Track current variant for all variant types
    if (variant) {
        currentVariant = variant;
    }

    if (variant === '3check' && checks) {
        document.getElementById('whiteChecks').textContent = (3 - checks.white); // checks delivered by White
        document.getElementById('blackChecks').textContent = (3 - checks.black); // checks delivered by Black
        checkCounters.style.display = 'flex';
    } else {
        checkCounters.style.display = 'none';
    }
}

// Speech/audio toggles for the web client.
var speechMuted = true;
var backendAudioMuted = true;
var backendAudioQueue = [];
var backendAudioPlaying = false;
var backendAudioElement = null;

function isCurrentAudioMuted() {
    if (webAudioMode === "backend") {
        return backendAudioMuted;
    }
    if (webAudioMode === "tts") {
        return speechMuted;
    }
    return true;
}

var speechAvailable = true
if (typeof speechSynthesis === "undefined") {
    speechAvailable = false
}
if (speechAvailable) {
    var myvoice = "";
    var voices = speechSynthesis.getVoices();
    // for Safari we need to pick an English voice explicitly, otherwise the system default is used
    for (i = 0; i < voices.length; i++) {
        if (voices[i].lang == "en-US") {
            myvoice = voices[i];
            break;
        }
    }
}

function talk(text) {
    if (speechAvailable && !speechMuted) {
        var msg = new SpeechSynthesisUtterance(text);
        msg.lang = "en-US";
        if (myvoice != "") {
            msg.voice = myvoice;
        }
        window.speechSynthesis.speak(msg);
    }
}

function stopBackendAudioPlayback() {
    backendAudioQueue = [];
    backendAudioPlaying = false;
    if (backendAudioElement) {
        backendAudioElement.pause();
        backendAudioElement.src = "";
        backendAudioElement = null;
    }
}

function playNextBackendAudio() {
    if (webAudioMode !== "backend" || backendAudioMuted || backendAudioPlaying || backendAudioQueue.length === 0) {
        return;
    }

    var clip = backendAudioQueue.shift();
    if (!clip || !clip.base64) {
        return;
    }

    backendAudioPlaying = true;
    backendAudioElement = new Audio("data:" + (clip.mime_type || "audio/ogg") + ";base64," + clip.base64);
    if (clip.rate && clip.rate > 0) {
        backendAudioElement.playbackRate = clip.rate;
    }
    backendAudioElement.onended = function () {
        backendAudioPlaying = false;
        backendAudioElement = null;
        playNextBackendAudio();
    };
    backendAudioElement.onerror = function () {
        backendAudioPlaying = false;
        backendAudioElement = null;
        playNextBackendAudio();
    };
    var playPromise = backendAudioElement.play();
    if (playPromise && typeof playPromise.catch === "function") {
        playPromise.catch(function () {
            backendAudioPlaying = false;
            backendAudioElement = null;
        });
    }
}

function queueBackendAudio(clip) {
    if (webAudioMode !== "backend" || backendAudioMuted) {
        return;
    }
    backendAudioQueue.push(clip);
    playNextBackendAudio();
}

function setSpeechMuted(muted) {
    var isMuted = !!muted;
    if (webAudioMode === "backend") {
        backendAudioMuted = isMuted;
        if (backendAudioMuted) {
            stopBackendAudioPlayback();
        }
    } else {
        speechMuted = isMuted || webAudioMode !== "tts";
        if (speechMuted && speechAvailable) {
            speechSynthesis.cancel();
        }
    }
    var muteButton = document.getElementById('btn-mute');
    if (muteButton && webAudioMode !== "off") {
        muteButton.classList.toggle('is-muted', isCurrentAudioMuted());
    }
}

talk("Hello, welcome to Picochess!");

function saymove(move, board) {
    var pnames = {
        "p": "pawn",
        "n": "knight",
        "b": "bishop",
        "r": "rook",
        "q": "queen",
        "k": "king",
    };
    talk(pnames[move.piece] + " from " + move.from + " to " + move.to + ".");
    if (move.color == "b") {
        var sidm = "Black";
    } else {
        var sidm = "White";
    }
    if (move.flags.includes("e")) {
        talk("Pawn takes pawn.");
    } else if (move.flags.includes("c")) {
        talk(pnames[move.piece] + " takes " + pnames[move.captured] + ".");
    } else if (move.flags.includes("k")) {
        talk(sidm + " castles kingside.");
    } else if (move.flags.includes("q")) {
        talk(sidm + " castles queenside.");
    }

    if (board.in_checkmate()) {
        talk("Checkmate!");
    } else if (board.in_check()) {
        talk("Check!");
    }
}

const NAG_FORCED_MOVE = 7;
const NAG_SINGULAR_MOVE = 8;
const NAG_WORST_MOVE = 9;
const NAG_DRAWISH_POSITION = 10;
const NAG_QUIET_POSITION = 11;
const NAG_ACTIVE_POSITION = 12;
const NAG_UNCLEAR_POSITION = 13;
const NAG_WHITE_SLIGHT_ADVANTAGE = 14;

// Explicitly initialize engine analysis state to avoid accidental auto-start.
window.analysis = false;
const NAG_BLACK_SLIGHT_ADVANTAGE = 15;

//# TODO: Add more constants for example from
//# https://en.wikipedia.org/wiki/Numeric_Annotation_Glyphs

const NAG_WHITE_MODERATE_COUNTERPLAY = 132;
const NAG_BLACK_MODERATE_COUNTERPLAY = 133;
const NAG_WHITE_DECISIVE_COUNTERPLAY = 134;
const NAG_BLACK_DECISIVE_COUNTERPLAY = 135;
const NAG_WHITE_MODERATE_TIME_PRESSURE = 136;
const NAG_BLACK_MODERATE_TIME_PRESSURE = 137;
const NAG_WHITE_SEVERE_TIME_PRESSURE = 138;
const NAG_BLACK_SEVERE_TIME_PRESSURE = 139;

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

var boardStatusEl = $('#BoardStatus'),
    dgtClockStatusEl = $('#DGTClockStatus'),
    dgtClockTextEl = $('#DGTClockText'),
    pgnEl = $('#pgn');
moveListEl = $('#moveList')

var gameHistory, fenHash, currentPosition;
const SERVER_NAME = location.hostname
// Opening book and games database servers
const BOOK_SERVER_PREFIX = ''; // same origin
const GAMES_SERVER_PREFIX = 'http://' + SERVER_NAME + ':7778';

fenHash = {};

currentPosition = {};
currentPosition.fen = START_FEN;

gameHistory = currentPosition;
gameHistory.gameHeader = '';
gameHistory.result = '';
gameHistory.variations = [];

var setupBoardFen = START_FEN;
var dataTableFen = START_FEN;

// web-specific opening book selection (independent from engine)
var webBookList = [];
var webBookStorageKey = 'webBookIndexV2';
var currentWebBookIndex = parseInt(localStorage.getItem(webBookStorageKey)) || 0;
var chessGameType = 0; // 0=Standard ; 1=Chess960
var computerside = ""; // color played by the computer

function removeHighlights() {
    if (highlight_move == HIGHLIGHT_ON) {
        chessground1.set({ lastMove: [] });
    }
}

function highlightBoard(ucimove, play) {
    if (highlight_move == HIGHLIGHT_ON) {
        var move = ucimove.match(/.{2}/g);
        chessground1.set({ lastMove: [move[0], move[1]] });
    }
}

function removeArrow() {
    chessground1.setShapes([]);
}

function addArrow(ucimove, play) {
    var move = ucimove.match(/.{2}/g);
    var brush = 'green';
    if (play === 'computer') {
        brush = 'yellow';
    }
    if (play === 'review') {
        brush = 'blue';
    }
    var shapes = { orig: move[0], dest: move[1], brush: brush };
    chessground1.setShapes([shapes]);
}

function figurinizeMove(move) {
    if (!move) { return; }
    move = move.replace('N', '<span class="figurine">&#9816;</span>');
    move = move.replace('B', '<span class="figurine">&#9815;</span>');
    move = move.replace('R', '<span class="figurine">&#9814;</span>');
    move = move.replace('K', '<span class="figurine">&#9812;</span>');
    move = move.replace('Q', '<span class="figurine">&#9813;</span>');
    move = move.replace('X', '<span class="figurine">&#9888;</span>'); // error code
    return move;
}

function isLightTheme() {
    var bgcolor = $('body').css("background-color")
    const [r, g, b, a] = bgcolor.match(/[\d\.]+/g).map(Number);
    return r > 127 && g > 127 && b > 127;
}

function updateBookHeader(book) {
    if (!book) {
        return;
    }
    var label = (book.label || '').trim();
    var file = (book.file || '').trim();

    if (!label && file) {
        var parts = file.split(/[\\/]/);
        label = parts[parts.length - 1].replace(/\.bin$/i, '');
    }
    if (!label) {
        label = 'No book';
    }

    $('#currentBookName').text(label);
    $('#currentBookContainer').removeClass('d-none');
}

function loadWebBookList() {
    $.getJSON('/book', { action: 'get_book_list' }, function (data) {
        if (data && data.books) {
            webBookList = data.books;
            var storedIndex = parseInt(localStorage.getItem(webBookStorageKey));
            if (Number.isFinite(storedIndex) && storedIndex >= 0 && storedIndex < webBookList.length) {
                currentWebBookIndex = storedIndex;
            } else if (typeof data.current_index === 'number') {
                currentWebBookIndex = data.current_index;
            } else {
                currentWebBookIndex = 0;
            }
            localStorage.setItem(webBookStorageKey, currentWebBookIndex);
            if (webBookList.length) {
                updateBookHeader(webBookList[currentWebBookIndex]);
            }
            bookDataTable.ajax.reload();
        }
    });
}

function changeWebBook(delta) {
    if (!webBookList.length) { return; }
    var nextIndex = (currentWebBookIndex + delta + webBookList.length) % webBookList.length;
    currentWebBookIndex = nextIndex;
    localStorage.setItem(webBookStorageKey, currentWebBookIndex);
    $.getJSON('/book',
        { action: 'set_book_index', index: nextIndex },
        function (data) {
            if (data && data.book) {
                updateBookHeader(data.book);
            } else if (webBookList.length) {
                updateBookHeader(webBookList[nextIndex]);
            }
            bookDataTable.ajax.reload();
        }
    );
}

var bookDataTable = $('#BookTable').DataTable({
    'processing': false,
    'paging': false,
    'info': false,
    'searching': false,
    'order': [
        [1, 'desc']
    ],
    'columnDefs': [{
        className: 'dt-center zero-border-right bookMoves',
        'targets': 0
    }, {
        className: 'dt-right zero-border-right',
        'targets': 1
    }],
    'ajax': {
        'url': BOOK_SERVER_PREFIX + '/book',
          'dataSrc': function (json) {
              if (json && json.book) {
                  updateBookHeader(json.book);
              }
              return (json && json.data) ? json.data : [];
          },
          'data': function (d) {
              d.action = 'get_book_moves';
              d.fen = dataTableFen;
              d.book_index = currentWebBookIndex;
          },
        'error': function (xhr, error, thrown) {
            // Silenciar errores de conexión a servidor de libros
        }
    },
    'columns': [
        {
            data: 'move',
            render: function (data, type, row) {
                if (currentPosition) {
                    var tmp_board = new Chess(currentPosition.fen, chessGameType);
                    move = tmp_board.move({ from: data.slice(0, 2), to: data.slice(2, 4), promotion: data.slice(4) });
                    if (move) {
                        return figurinizeMove(move.san);
                    }
                }
                return data;
            }
        },
        { data: 'count', render: $.fn.dataTable.render.number(',', '.') },
        {
            data: 'draws',
            render: function (data, type, row) { return "" },
            createdCell: function (td, cellData, rowData, row, col) {
                var canvas = jQuery("<canvas id=\"white_draws_black\"></canvas>");
                canvas.appendTo(jQuery(td));

                ctx = $(canvas).get(0).getContext("2d");
                ctx.fillStyle = '#bfbfbf'; // border color for dark theme
                if (isLightTheme()) {
                    // border color for light theme
                    ctx.fillStyle = '#4f4f4f';
                }
                ctx.fillRect(0, 0, 300, 150); // border
                var height = 130;
                var maxWidth = 298;
                var top = 10
                whiteWins = rowData['whitewins']
                whiteWidth = maxWidth * whiteWins / 100;
                ctx.fillStyle = '#ffffff';
                ctx.fillRect(1, top, whiteWidth, height); // white wins
                draws = cellData;
                if ((100 - whiteWins - draws) == 1) { // take care of rounding errors
                    draws++;
                }
                drawsWidth = maxWidth * draws / 100;
                ctx.fillStyle = '#bfbfbf';
                ctx.fillRect(whiteWidth + 1, top, drawsWidth, height); // draws
                ctx.fillStyle = '#000000';
                ctx.fillRect(whiteWidth + drawsWidth + 1, top, maxWidth - whiteWidth - drawsWidth, height); // black wins
            },
        },
    ]
});

var gameDataTable = $('#GameTable').DataTable({
    'processing': false,
    'paging': false,
    'info': false,
    'searching': false,
    'ordering': false,
    'select': { items: 'row', style: 'single', toggleable: false },
    'columnDefs': [{
        className: 'result',
        'targets': 2
    }],
    'ajax': {
        'url': GAMES_SERVER_PREFIX + '/query',
        'dataSrc': 'data',
        'data': function (d) {
            d.action = 'get_games';
            d.fen = dataTableFen;
        },
        'error': function (xhr, error, thrown) {
            // Silenciar errores de conexión a servidores auxiliares
        }
    },
    'columns': [
        { data: 'white' },
        { data: 'black' },
        { data: 'result', render: function (data, type, row) { return data.replace('1/2-1/2', '\u00BD'); } },
        { data: 'event' }
    ]
});

gameDataTable.on('select', function (e, dt, type, indexes) {
    var data = gameDataTable.rows(indexes).data().pluck('pgn')[0].split("\n");
    loadGame(data);
    updateStatus();
    removeHighlights();
});

// do not pick up pieces if the game is over
// only pick up pieces for the side to move
function createGamePointer() {
    var tmpGame;

    if (currentPosition && currentPosition.fen) {
        tmpGame = new Chess(currentPosition.fen, chessGameType);
    }
    else {
        tmpGame = new Chess(setupBoardFen, chessGameType);
    }
    return tmpGame;
}

function stripFen(fen) {
    var strippedFen = fen.replace(/\//g, '');
    strippedFen = strippedFen.replace(/ /g, '');
    return strippedFen;
}

String.prototype.trim = function () {
    return this.replace(/\s*$/g, '');
};

function WebExporter(columns) {
    this.lines = [];
    this.columns = columns;
    this.current_line = '';
    this.flush_current_line = function () {
        if (this.current_line) {
            this.lines.append(this.current_line.trim());
            this.current_line = '';
        }
    };

    this.write_token = function (token) {
        if (this.columns && this.columns - this.current_line.length < token.length) {
            this.flush_current_line();
        }
        this.current_line += token;
    };

    this.write_line = function (line) {
        this.flush_current_line();
        this.lines.push(line.trim());
    };

    this.start_game = function () { };

    this.end_game = function () {
        this.write_line();
    };

    this.start_headers = function () { };

    this.end_headers = function () {
        this.write_line();
    };

    this.start_variation = function () {
        this.write_token('<span class="gameVariation"> [ ');
    };

    this.end_variation = function () {
        this.write_token(' ] </span>');
    };

    this.put_starting_comment = function (comment) {
        this.put_comment(comment);
    };

    this.put_comment = function (comment) {
        this.write_token('<span class="gameComment"><a href="#" class="comment"> ' + comment + ' </a></span>');
    };

    this.put_nags = function (nags) {
        if (nags) {
            nags = nags.sort();

            for (var i = 0; i < nags.length; i++) {
                this.put_nag(nags[i]);
            }
        }
    };

    this.put_nag = function (nag) {
        var int_nag = parseInt(nag);
        if (simpleNags[int_nag]) {
            this.write_token(" " + simpleNags[int_nag] + " ");
        }
        else {
            this.write_token("$" + String(nag) + " ");
        }
    };

    this.put_fullmove_number = function (turn, fullmove_number, variation_start) {
        if (turn === 'w') {
            this.write_token(String(fullmove_number) + ". ");
        }
        else if (variation_start) {
            this.write_token(String(fullmove_number) + "... ");
        }
    };

    this.put_move = function (board, m) {
        var old_fen = board.fen();
        var tmp_board = new Chess(old_fen, chessGameType);
        var out_move = tmp_board.move(m);
        var fen = tmp_board.fen();
        var stripped_fen = stripFen(fen);
        if (!out_move) {
            console.warn('put_move error');
            console.log(board.ascii());
            console.log(board.moves());
            console.log(tmp_board.ascii());
            console.log(m);
            out_move = { 'san': 'X' + m.from + m.to };
        }
        this.write_token('<span class="gameMove' + (board.fullmove_number) + '"><a href="#" class="fen" data-fen="' + fen + '" id="' + stripped_fen + '"> ' + figurinizeMove(out_move.san) + ' </a></span>');
    };

    this.put_result = function (result) {
        this.write_token(result + " ");
    };

    // toString override
    this.toString = function () {
        if (this.current_line) {
            var tmp_lines = this.lines.slice(0);
            tmp_lines.push(this.current_line.trim());

            return tmp_lines.join("\n").trim();
        }
        else {
            return this.lines.join("\n").trim();
        }
    };
}

function PgnExporter(columns) {
    this.lines = [];
    this.columns = columns;
    this.current_line = "";
    this.flush_current_line = function () {
        if (this.current_line) {
            this.lines.append(this.current_line.trim());
            this.current_line = "";
        }
    };

    this.write_token = function (token) {
        if (this.columns && this.columns - this.current_line.length < token.length) {
            this.flush_current_line();
        }
        this.current_line += token;
    };

    this.write_line = function (line) {
        this.flush_current_line();
        this.lines.push(line.trim());
    };

    this.start_game = function () { };

    this.end_game = function () {
        this.write_line();
    };

    this.start_headers = function () { };

    this.put_header = function (tagname, tagvalue) {
        this.write_line("[{0} \"{1}\"]".format(tagname, tagvalue));
    };

    this.end_headers = function () {
        this.write_line();
    };

    this.start_variation = function () {
        this.write_token("( ");
    };

    this.end_variation = function () {
        this.write_token(") ");
    };

    this.put_starting_comment = function (comment) {
        this.put_comment(comment);
    };

    this.put_comment = function (comment) {
        this.write_token("{ " + comment.replace("}", "").trim() + " } ");
    };

    this.put_nags = function (nags) {
        if (nags) {
            nags = nags.sort();

            for (var i = 0; i < nags.length; i++) {
                this.put_nag(nags[i]);
            }
        }
    };

    this.put_nag = function (nag) {
        this.write_token("$" + String(nag) + " ");
    };

    this.put_fullmove_number = function (turn, fullmove_number, variation_start) {
        if (turn === 'w') {
            this.write_token(String(fullmove_number) + ". ");
        }
        else if (variation_start) {
            this.write_token(String(fullmove_number) + "... ");
        }
    };

    this.put_move = function (board, m) {
        var tmp_board = new Chess(board.fen(), chessGameType);
        var out_move = tmp_board.move(m);
        if (!out_move) {
            console.warn('put_move error');
            console.log(tmp_board.ascii());
            console.log(m);
            out_move = { 'san': 'X' + m.from + m.to };
        }
        this.write_token(out_move.san + " ");
    };

    this.put_result = function (result) {
        this.write_token(result + " ");
    };

    // toString override
    this.toString = function () {
        if (this.current_line) {
            var tmp_lines = this.lines.slice(0);
            tmp_lines.push(this.current_line.trim());

            return tmp_lines.join("\n").trim();
        }
        else {
            return this.lines.join("\n").trim();
        }
    };
}

function exportGame(root_node, exporter, include_comments, include_variations, _board, _after_variation) {
    if (_board === undefined) {
        _board = new Chess(root_node.fen, chessGameType);
    }

    // append fullmove number
    if (root_node.variations && root_node.variations.length > 0) {
        _board.fullmove_number = Math.ceil(root_node.variations[0].half_move_num / 2);

        var main_variation = root_node.variations[0];
        exporter.put_fullmove_number(_board.turn(), _board.fullmove_number, _after_variation);
        exporter.put_move(_board, main_variation.move);
        if (include_comments) {
            exporter.put_nags(main_variation.nags);
            // append comment
            if (main_variation.comment) {
                exporter.put_comment(main_variation.comment);
            }
        }
    }

    // Then export sidelines.
    if (include_variations && root_node.variations) {
        for (var j = 1; j < root_node.variations.length; j++) {
            var variation = root_node.variations[j];
            exporter.start_variation();

            if (include_comments && variation.starting_comment) {
                exporter.put_starting_comment(variation.starting_comment);
            }
            exporter.put_fullmove_number(_board.turn(), _board.fullmove_number, true);

            exporter.put_move(_board, variation.move);

            if (include_comments) {
                // Append NAGs.
                exporter.put_nags(variation.nags);

                // Append the comment.
                if (variation.comment) {
                    exporter.put_comment(variation.comment);
                }
            }
            // Recursively append the next moves.
            _board.move(variation.move);
            exportGame(variation, exporter, include_comments, include_variations, _board, false);
            _board.undo();

            // End variation.
            exporter.end_variation();
        }
    }

    // The mainline is continued last.
    if (root_node.variations && root_node.variations.length > 0) {
        main_variation = root_node.variations[0];

        // Recursively append the next moves.
        _board.move(main_variation.move);
        _after_variation = (include_variations && (root_node.variations.length > 1));
        exportGame(main_variation, exporter, include_comments, include_variations, _board, _after_variation);
        _board.undo();
    }
}

function writeVariationTree(dom, gameMoves, gameHistoryEl) {
    $(dom).html(gameHistoryEl.gameHeader + '<div class="gameMoves">' + gameMoves + ' <span class="gameResult">' + gameHistoryEl.result + '</span></div>');
}

// update the board position after the piece snap
// for castling, en passant, pawn promotion
function updateCurrentPosition(move, tmpGame) {
    var foundMove = false;
    if (currentPosition && currentPosition.variations) {
        for (var i = 0; i < currentPosition.variations.length; i++) {
            if (move.san === currentPosition.variations[i].move.san) {
                currentPosition = currentPosition.variations[i];
                foundMove = true;
            }
        }
    }
    if (!foundMove) {
        var __ret = addNewMove({ 'move': move }, currentPosition, tmpGame.fen());
        currentPosition = __ret.node;
        var exporter = new WebExporter();
        exportGame(gameHistory, exporter, true, true, undefined, false);
        writeVariationTree(pgnEl, exporter.toString(), gameHistory);
    }
}

var updateStatus = function () {
    var status = '';
    $('.fen').unbind('click', goToGameFen).one('click', goToGameFen);

    var moveColor = 'White';
    var tmpGame = createGamePointer();
    var fen = tmpGame.fen();

    var strippedFen = stripFen(fen);

    // squares for dark mode
    var whiteSquare = 'fa-square-o'
    var blackSquare = 'fa-square'
    if (isLightTheme()) {
        // squares for light mode
        whiteSquare = 'fa-square';
        blackSquare = 'fa-square-o';
    }
    if (tmpGame.turn() === 'b') {
        moveColor = 'Black';
        $('#sidetomove').html("<i class=\"fa " + whiteSquare + " fa-lg\"></i>");
    }
    else {
        $('#sidetomove').html("<i class=\"fa " + blackSquare + " fa-lg\"></i>");
    }

    // checkmate?
    if (tmpGame.in_checkmate() === true) {
        status = moveColor + ' (mate)';
    }
    // draw?
    else if (tmpGame.in_draw() === true) {
        status = moveColor + ' (draw)';
    }
    // game still on
    else {
        status = moveColor;
        // check?
        if (tmpGame.in_check() === true) {
            status += ' (check)';
        }
    }

    boardStatusEl.html(status);
    if (window.analysis === true) {
        analyze(true);
    }

    dataTableFen = fen;


    if ($('#' + strippedFen).length) {
        var element = $('#' + strippedFen);
        $(".fen").each(function () {
            $(this).removeClass('text-warning');
        });
        element.addClass('text-warning');

        // Keep scrolling constrained to the move list and avoid scrolling the whole page on mobile.
        var moveList = document.getElementById('moveList');
        if (moveList) {
            var rowRect = element[0].getBoundingClientRect();
            var listRect = moveList.getBoundingClientRect();
            var margin = 10;
            if (rowRect.top < listRect.top) {
                moveList.scrollTop -= (listRect.top - rowRect.top) + margin;
            } else if (rowRect.bottom > listRect.bottom) {
                moveList.scrollTop += (rowRect.bottom - listRect.bottom) + margin;
            }
        }
    }

    // Skip book and games database lookups for atomic chess — the databases
    // contain standard-chess data and the FEN after explosions will not match.
    if (currentVariant !== 'atomic' && currentVariant !== 'racingkings') {
        bookDataTable.ajax.reload();
        gameDataTable.ajax.reload();
    }
};

function toDests(chess) {
    var dests = {};
    chess.SQUARES.forEach(function (s) {
        var ms = chess.moves({ square: s, verbose: true });
        if (ms.length)
            dests[s] = ms.map(function (m) { return m.to; });
    });
    return dests;
}

function toColor(chess) {
    return (chess.turn() === 'w') ? 'white' : 'black';
}

var onSnapEnd = async function (source, target) {
    stopAnalysis();
    var tmpGame = createGamePointer();

    if (!currentPosition) {
        currentPosition = {};
        currentPosition.fen = tmpGame.fen();
        gameHistory = currentPosition;
        gameHistory.gameHeader = '<h4>Player (-) vs Player (-)</h4><h5>Board game</h5>';
        gameHistory.result = '*';
    }

    var move = await getMove(tmpGame, source, target);

    updateCurrentPosition(move, tmpGame);
    updateChessGround();
    $.post('/channel', {
        action: 'move', fen: currentPosition.fen, source: source, target: target,
        promotion: move.promotion ? move.promotion : ''
    }, function (data) { });
    updateStatus();
};

async function promotionDialog(ucimove) {
    var move = ucimove.match(/.{2}/g);
    var source = move[0];
    var target = move[1];

    var tmpGame = createGamePointer();
    var move = await getMove(tmpGame, source, target);
    if (move !== null) {
        $.post('/channel', {
            action: 'promotion', fen: currentPosition.fen, source: source, target: target,
            promotion: move.promotion ? move.promotion : ''
        }, function (data) { });
    }
}

async function getMove(game, source, target) {
    let promotion = null
    if (isPromotion(game.get(source), target)) {
        chessground1.set({ animation: { enabled: false } })
        promotion = await getUserPromotion(target)
        chessground1.set({ animation: { enabled: true } })
    }

    return game.move({
        from: source,
        to: target,
        promotion: promotion
    });
}

function updateChessGround() {
    var tmpGame = createGamePointer();
    var psi = window._picoSystemInfo || {};
    var hasBoard = !!psi.has_board;
    var turnColor = toColor(tmpGame);
    var movableColor;

    if (!hasBoard) {
        // No physical board: full diagram interactivity (NOEBOARD mode).
        movableColor = turnColor;
    } else if (psi.interaction_mode === 'remote') {
        // REMOTE mode: local player uses the physical board; the remote
        // opponent enters moves via the web diagram.  Only allow dragging
        // when it is actually the remote side's turn.
        var remoteColor = (psi.play_mode === 'user_white') ? 'black' : 'white';
        movableColor = (turnColor === remoteColor) ? remoteColor : 'none';
    } else {
        // Any other mode with a board: diagram is read-only.
        movableColor = 'none';
    }

    chessground1.set({
        fen: currentPosition.fen,
        turnColor: turnColor,
        movable: {
            color: movableColor,
            dests: (movableColor === 'none') ? {} : toDests(tmpGame)
        }
    });
}

function playOtherSide() {
    return onSnapEnd;
}

var cfg3 = {
    movable: {
        color: 'white',
        free: false,
        dests: toDests(Chess())
    }
};

var chessground1 = new Chessground(document.getElementById('board'), cfg3);

chessground1.set({
    movable: { events: { after: playOtherSide() } }
});

$(window).resize(function () {
    chessground1.redrawAll();
});

function addNewMove(m, current_position, fen, props) {
    var node = {};
    node.variations = [];

    node.move = m.move;
    node.previous = current_position;
    node.nags = [];
    if (props) {
        if (props.comment) {
            node.comment = props.comment;
        }
        if (props.starting_comment) {
            node.starting_comment = props.starting_comment;
        }
    }

    if (current_position && current_position.previous) {
        node.half_move_num = node.previous.half_move_num + 1;
    }
    else {
        node.half_move_num = 1;
    }
    node.fen = fen;
    if ($.isEmptyObject(fenHash)) {
        fenHash['first'] = node.previous;
        node.previous.fen = setupBoardFen;
    }
    fenHash[node.fen] = node;
    if (current_position) {
        if (!current_position.variations) {
            current_position.variations = [];
        }
        current_position.variations.push(node);
    }
    return { node: node, position: current_position };
}

function loadGame(pgn_lines) {
    fenHash = {};

    var curr_fen;
    if (currentPosition) {
        curr_fen = currentPosition.fen;
    }
    else {
        curr_fen = START_FEN;
    }

    gameHistory.previous = null;
    currentPosition = {};
    var current_position = currentPosition;
    gameHistory = current_position;

    var game_body_regex = /(%.*?[\n\r])|(\{[\s\S]*?\})|(\$[0-9]+)|(\()|(\))|(\*|1-0|0-1|1\/2-1\/2)|([NBKRQ]?[a-h]?[1-8]?[\-x]?[a-h][1-8](?:=?[nbrqNBRQ])?[\+]?|--|O-O(?:-O)?|0-0(?:-0)?)|([\?!]{1,2})/g;
    var game_header_regex = /\[([A-Za-z0-9]+)\s+\"(.*)\"\]/;

    var line;
    var parsed_headers = false;
    var game_headers = {};
    var game_body = '';
    for (var j = 0; j < pgn_lines.length; j++) {
        line = pgn_lines[j];
        // Parse headers first, then game body
        if (!parsed_headers) {
            if ((result = game_header_regex.exec(line)) !== null) {
                game_headers[result[1]] = result[2];
            }
            else {
                parsed_headers = true;
            }
        }
        if (parsed_headers) {
            game_body += line + "\n";
        }
    }

    var tmpGame;
    if ('FEN' in game_headers && 'SetUp' in game_headers) {
        if ('Variant' in game_headers && 'Chess960' === game_headers['Variant']) {
            chessGameType = 1; // values from chess960.js
        } else {
            chessGameType = 0;
        }
        tmpGame = new Chess(game_headers['FEN'], chessGameType);
        setupBoardFen = game_headers['FEN'];
    }
    else {
        tmpGame = new Chess();
        setupBoardFen = START_FEN;
        chessGameType = 0;
    }

    var board_stack = [tmpGame];
    var variation_stack = [current_position];
    var last_board_stack_index;
    var last_variation_stack_index;

    var in_variation = false;
    var starting_comment = '';

    var result;
    var lastmove;
    while ((result = game_body_regex.exec(game_body)) !== null) {

        var token = result[0];
        var comment;

        if (token === '1-0' || token === '0-1' || token === '1/2-1/2' || token === '*') {
            game_headers['Result'] = token;
        }
        else if (token[0] === '{') {
            last_variation_stack_index = variation_stack.length - 1;

            comment = token.substring(1, token.length - 1);
            comment = comment.replace(/\n|\r/g, " ");

            if (in_variation || !variation_stack[last_variation_stack_index].previous) {
                if (variation_stack[last_variation_stack_index].comment) {
                    variation_stack[last_variation_stack_index].comment = variation_stack[last_variation_stack_index].comment + " " + comment;
                }
                else {
                    variation_stack[last_variation_stack_index].comment = comment;
                }
                comment = undefined;
            }
            else {
                if (starting_comment.length > 0) {
                    comment = starting_comment + " " + comment;
                }
                starting_comment = comment;
                comment = undefined;
            }
        }
        else if (token === '(') {
            last_board_stack_index = board_stack.length - 1;
            last_variation_stack_index = variation_stack.length - 1;

            if (variation_stack[last_variation_stack_index].previous) {
                variation_stack.push(variation_stack[last_variation_stack_index].previous);
                last_variation_stack_index += 1;
                board_stack.push(Chess(variation_stack[last_variation_stack_index].fen));
                in_variation = false;
            }
        }
        else if (token === ')') {
            if (variation_stack.length > 1) {
                variation_stack.pop();
                board_stack.pop();
            }
        }
        else if (token[0] === '$') {
            variation_stack[variation_stack.length - 1].nags.push(token.slice(1));
        }
        else if (token === '?') {
            variation_stack[variation_stack.length - 1].nags.push(NAG_MISTAKE);
        }
        else if (token === '??') {
            variation_stack[variation_stack.length - 1].nags.push(NAG_BLUNDER);
        }
        else if (token === '!') {
            variation_stack[variation_stack.length - 1].nags.push(NAG_GOOD_MOVE);
        }
        else if (token === '!!') {
            variation_stack[variation_stack.length - 1].nags.push(NAG_BRILLIANT_MOVE);
        }
        else if (token === '!?') {
            variation_stack[variation_stack.length - 1].nags.push(NAG_SPECULATIVE_MOVE);
        }
        else if (token === '?!') {
            variation_stack[variation_stack.length - 1].nags.push(NAG_DUBIOUS_MOVE);
        }
        else {
            last_board_stack_index = board_stack.length - 1;
            last_variation_stack_index = variation_stack.length - 1;

            var preparsed_move = token;
            var move = board_stack[last_board_stack_index].move(preparsed_move, { sloppy: true });
            in_variation = true;
            if (move === null) {
                // Variant chess (e.g. atomic): chess.js cannot validate moves
                // that are only legal under variant rules (explosions clear
                // pieces that chess.js still thinks are on the board).  Skip
                // the move so we don't corrupt fenHash; forcePosition() will
                // set the correct board state later.
                console.log('Unparsed move (variant?): ' + preparsed_move);
                console.log('Fen: ' + board_stack[last_board_stack_index].fen());
                continue;
            }

            var props = {};
            if (comment) {
                props.comment = comment;
                comment = undefined;
            }
            if (starting_comment) {
                props.starting_comment = starting_comment;
                starting_comment = '';
            }
            lastmove = move;

            var __ret = addNewMove({ 'move': move }, variation_stack[last_variation_stack_index], board_stack[last_board_stack_index].fen(), props);
            variation_stack[last_variation_stack_index] = __ret.node;
        }
    }
    if (lastmove && (computerside == "" || (computerside != "" && lastmove.color != computerside))) {
        var tmp_board = new Chess(currentPosition.fen, chessGameType);
        saymove(lastmove, tmp_board); // announce user move
    }
    fenHash['last'] = fenHash[tmpGame.fen()];

    if (curr_fen === undefined) {
        currentPosition = fenHash['first'];
    }
    else {
        currentPosition = fenHash[curr_fen];
    }
    setHeaders(game_headers);
    $('.fen').unbind('click', goToGameFen).one('click', goToGameFen);
}

function getFullGame() {
    var gameHeader = getPgnGameHeader(gameHistory.originalHeader);
    if (gameHeader.length <= 1) {
        gameHistory.originalHeader = {
            'White': '*',
            'Black': '*',
            'Event': '?',
            'Site': '?',
            'Date': '?',
            'Round': '?',
            'Result': '*',
            'BlackElo': '-',
            'WhiteElo': '-',
            'Time': '00:00:00'
        };
        gameHeader = getPgnGameHeader(gameHistory.originalHeader);
    }

    var exporter = new PgnExporter();
    exportGame(gameHistory, exporter, true, true, undefined, false);
    var exporterContent = exporter.toString();
    return gameHeader + exporterContent;
}

function getPgnGameHeader(h) {
    var gameHeaderText = '';
    for (var key in h) {
        // hasOwnProperty ensures that inherited properties are not included
        if (h.hasOwnProperty(key)) {
            var value = h[key];
            gameHeaderText += "[" + key + " \"" + value + "\"]\n";
        }
    }
    gameHeaderText += "\n";
    return gameHeaderText;
}

function getWebGameHeader(h) {
    var gameHeaderText = '';
    gameHeaderText += '<h4>' + h.White + ' (' + h.WhiteElo + ') vs ' + h.Black + ' (' + h.BlackElo + ')</h4>';
    gameHeaderText += '<h5>' + h.Event + ', ' + h.Site + ' ' + h.Date + '</h5>';
    return gameHeaderText;
}

function download() {
    var content = getFullGame();
    var dl = document.createElement('a');
    dl.setAttribute('href', 'data:text/plain;charset=utf-8,' + encodeURIComponent(content));
    dl.setAttribute('download', 'game.pgn');
    document.body.appendChild(dl);
    dl.click();
}

function newBoard(fen) {
    stopAnalysis();

    fenHash = {};
    computerside = "";

    currentPosition = {};
    currentPosition.fen = fen;

    setupBoardFen = fen;
    gameHistory = currentPosition;
    gameHistory.gameHeader = '';
    gameHistory.result = '';
    gameHistory.variations = [];

    updateChessGround();
    updateStatus();
    removeHighlights();
    removeArrow();
}

function clockButton0() {
    $.post('/channel', { action: 'clockbutton', button: 0 }, function (data) { });
}

function clockButton1() {
    $.post('/channel', { action: 'clockbutton', button: 1 }, function (data) { });
}

function clockButton2() {
    $.post('/channel', { action: 'clockbutton', button: 2 }, function (data) { });
}

function clockButton3() {
    $.post('/channel', { action: 'clockbutton', button: 3 }, function (data) { });
}

function clockButton4() {
    $.post('/channel', { action: 'clockbutton', button: 4 }, function (data) { });
}

function toggleLeverButton() {
    $('#leverDown').toggle();
    $('#leverUp').toggle();
    var button = 0x40;
    if ($('#leverDown').is(':hidden')) {
        button = -0x40;
    }
    $.post('/channel', { action: 'clockbutton', button: button }, function (data) { });
}

function clockButtonPower() {
    $.post('/channel', { action: 'clockbutton', button: 0x11 }, function (data) { });
}

function clockSwitchSides() {
    $.post('/channel', { action: 'clockbutton', button: 0x40 }, function (data) { });
    boardFlip();
}

function clockPauseResume() {
    $.post('/channel', { action: 'pause_resume' }, function (data) { });
}

function clockShowEvaluation() {
    clockButton1();
}

function clockShowHint() {
    clockButton3();
}

function goToPosition(fen) {
    stopAnalysis();
    currentPosition = fenHash[fen];
    if (!currentPosition) {
        return false;
    }
    updateChessGround();
    updateStatus();
    return true;
}

function goToGameFen() {
    var fen = $(this).attr('data-fen');
    goToPosition(fen);
    removeHighlights();
}

function goToStart() {
    removeHighlights();
    stopAnalysis();
    currentPosition = gameHistory;
    updateChessGround();
    updateStatus();
}

function goToEnd() {
    removeHighlights();
    stopAnalysis();
    if (fenHash.last) {
        currentPosition = fenHash.last;
        updateChessGround();
    }
    updateStatus();
}

function goForward() {
    removeHighlights();
    stopAnalysis();
    if (currentPosition && currentPosition.variations[0]) {
        currentPosition = currentPosition.variations[0];
        if (currentPosition) {
            updateChessGround();
        }
    }
    updateStatus();
}

function goBack() {
    removeHighlights();
    stopAnalysis();
    if (currentPosition && currentPosition.previous) {
        currentPosition = currentPosition.previous;
        updateChessGround();
    }
    updateStatus();
}

function boardFlip() {
    chessground1.toggleOrientation();
}

function receive_message(wsevent) {
    console.log("received message: " + wsevent.data);
    var msg_obj = $.parseJSON(wsevent.data);
    console.log(msg_obj.event);
    console.log(msg_obj);
    console.log(' ');
}

function formatEngineOutput(line) {
    if (!line) return null;
    if (line.search('depth') > 0 && line.search('currmove') < 0) {
        var analysis_game = new Chess();
        var start_move_num = 1;
        if (currentPosition && currentPosition.fen) {
            analysis_game.load(currentPosition.fen, chessGameType);
            start_move_num = getCountPrevMoves(currentPosition) + 1;
        }

        var output = '';
        var tokens = line.split(" ");
        var depth_index = tokens.indexOf('depth') + 1;
        var depth = tokens[depth_index];
        var score_index = tokens.indexOf('score') + 1;

        var multipv_index = tokens.indexOf('multipv');
        var multipv = 0;
        if (multipv_index > -1) {
            multipv = Number(tokens[multipv_index + 1]);
        }

        var token = tokens[score_index];
        var score = '?';
        var rawScore = 0;
        if (token === 'mate') {
            rawScore = parseInt(tokens[score_index + 1]);

            // Para mate, mantener el signo original del motor
            if (analysis_game.turn() === 'b') {
                rawScore *= -1;
            }
            score = '#' + rawScore;
        }
        else if (tokens[score_index + 1]) {
            rawScore = parseInt(tokens[score_index + 1]) / 100.0;

            // Invertir puntuación solo si le toca a las negras
            if (analysis_game.turn() === 'b') {
                rawScore *= -1;
            }
            score = rawScore.toFixed(2);
            if (token === 'lowerbound') {
                score = '>' + score;
            }
            if (token === 'upperbound') {
                score = '<' + score;
            }
        }

        var pv_index = tokens.indexOf('pv') + 1;

        var pv_out = tokens.slice(pv_index);

        var MAX_PV_MOVES = 8;                        // *** Limita PV max 8 movimientos.
        pv_out = pv_out.slice(0, MAX_PV_MOVES);
        var first_move = pv_out[0];
        for (var i = 0; i < pv_out.length; i++) {
            var from = pv_out[i].slice(0, 2);
            var to = pv_out[i].slice(2, 4);
            var promotion = '';
            if (pv_out[i].length === 5) {
                promotion = pv_out[i][4];
            }
            if (promotion) {
                var mv = analysis_game.move(({ from: from, to: to, promotion: promotion }));
            } else {
                analysis_game.move(({ from: from, to: to }));
            }
        }

        var history = analysis_game.history();
        window.engine_lines['import_pv_' + multipv] = { score: score, depth: depth, line: history };

        var turn_sep = '';
        if (start_move_num % 2 === 0) {
            turn_sep = '..';
        }

        // Determinar clase de puntuacion
        var scoreClass = 'score-display';
        var numericScore = parseFloat(score);
        if (String(score).includes('#')) {
            scoreClass += ' score-mate';
        } else if (numericScore > 0) {
            scoreClass += ' score-positive';
        } else if (numericScore < 0) {
            scoreClass += ' score-negative';
        }

        // Build score+depth meta HTML (shared for pv_1 update and pv_2+ header)
        var metaHtml = '';
        if (score !== null) {
            metaHtml += '<span class="' + scoreClass + '">' + score + '</span>';
        }
        metaHtml += '<span class="depth-display">d' + depth + '</span>';

        // Build PV body HTML
        var bodyHtml = '';
        if (history.length > 0) {
            var firstMoveText = '';
            var tempGame = new Chess();
            if (currentPosition && currentPosition.fen) {
                tempGame.load(currentPosition.fen, chessGameType);
            }
            var currentTurn = tempGame.turn();
            var moveNumber = Math.floor((start_move_num + 1) / 2);
            if (currentTurn === 'w') {
                firstMoveText += moveNumber + '. ';
            } else {
                firstMoveText += moveNumber + '... ';
            }
            firstMoveText += figurinizeMove(history[0]);
            bodyHtml += '<span class="first-move">' + firstMoveText + '</span>';
        }
        if (history.length > 1) {
            var continuationText = '';
            var currentMoveNum = start_move_num;
            for (i = 1; i < history.length; ++i) {
                currentMoveNum++;
                if (currentMoveNum % 2 === 1) {
                    continuationText += Math.floor((currentMoveNum + 1) / 2) + '. ';
                }
                continuationText += figurinizeMove(history[i]) + ' ';
            }
            bodyHtml += '<span class="continuation-moves">' + continuationText.trim() + '</span>';
        }

        analysis_game = null;

        if (multipv === 1) {
            // First PV: update the static SF18 row elements directly
            updateEvaluationBar(score);
            return { meta: metaHtml, body: bodyHtml, pv_index: 1 };
        }

        // Extra PV lines (pv_2+): same two-row layout as pv_1 but without buttons
        output = '<div class="pv-two-row">';
        output += '<div class="pv-header">';
        output += '<span class="engine-name-badge">Stockfish 18</span>';
        output += metaHtml;
        output += '</div>';
        output += '<div class="pv-body">' + bodyHtml + '</div>';
        output += '</div>';
        return { line: output, pv_index: multipv };
    }
    else if (line.search('currmove') < 0 && line.search('time') < 0) {
        return line;
    }
}

// Update vertical evaluation bar (black on top, white on bottom, like Lichess)
// +1.00 = one square shift; 0.00 = 50/50 split at mid-board
function updateEvaluationBar(score) {
    if (!score || score === '?') return;

    var numericScore = 0;
    var isMate = false;

    if (String(score).includes('#')) {
        isMate = true;
        var mateIn = parseInt(score.replace('#', ''));
        numericScore = mateIn > 0 ? 50 : -50;
    } else {
        numericScore = parseFloat(score);
    }

    var fillElement = $('#evaluationFill');

    var blackPct;
    if (isMate) {
        blackPct = numericScore > 0 ? 0 : 100;
    } else {
        numericScore = Math.max(-8, Math.min(8, numericScore));
        // Each pawn = 1/8 of bar height; 0.00 → 50%, +8 → 0%, -8 → 100%
        blackPct = (4 - numericScore) / 8 * 100;
    }

    fillElement.css('height', blackPct + '%');

    // Show numeric score as tooltip and small label
    var scoreText = String(score);
    var barEl = document.getElementById('evaluationBar');
    var valEl = document.getElementById('evaluationValue');
    if (barEl) {
        barEl.setAttribute('title', scoreText);
        barEl.setAttribute('aria-valuenow', isMate ? (numericScore > 0 ? 8 : -8) : numericScore);
        barEl.setAttribute('aria-valuetext', scoreText);
    }
    if (valEl) valEl.textContent = scoreText;
}

function multiPvIncrease() {
    if (isLocalWebClient()) {
        window.multipv = 1;
        updateSF18PmButtons();
        return;
    }

    window.multipv += 1;

    if (window.analysis) {
        // stopAnalysis() terminates the Worker and recreates pv_2..pv_N containers,
        // then analyze(true) creates a fresh Worker and restarts with new multipv.
        stopAnalysis();
        analyze(true);
    } else {
        var new_div_str = "<div id=\"pv_" + window.multipv + "\" class=\"pv-container\"></div>";
        $("#pv_output").append(new_div_str);
    }

    updateSF18PmButtons();
}

function multiPvDecrease() {
    if (isLocalWebClient()) {
        window.multipv = 1;
        updateSF18PmButtons();
        return;
    }

    if (window.multipv > 1) {
        window.multipv -= 1;

        if (window.analysis) {
            stopAnalysis();
            analyze(true);
        } else {
            $('#pv_' + (window.multipv + 1)).remove();
        }

        updateSF18PmButtons();
    }
}

function importPv(multipv) {
    stopAnalysis();
    var tmpGame = createGamePointer();
    var line = window.engine_lines['import_pv_' + multipv].line;
    for (var i = 0; i < line.length; ++i) {
        var text_move = line[i];
        var move = tmpGame.move(text_move);
        if (move) {
            updateCurrentPosition(move, tmpGame);
        } else {
            console.warn('import_pv error');
            console.log(tmpGame.ascii());
            console.log(text_move);
            break;
        }
    }
    updateChessGround();
    updateStatus();
}

function analyzePressed() {
    if (!window.analysis) {
        $('#evaluationBar').css('visibility', 'visible');
    } else {
        $('#evaluationBar').css('visibility', 'hidden');
        // Clear extra PV lines; pv_1 body is static HTML in sf18Row
        $('#pv_output').empty();
        for (var i = 2; i <= window.multipv; i++) {
            $('#pv_output').append('<div id="pv_' + i + '" class="pv-container"></div>');
        }
    }
    analyze(false);
}

function updateEngineControlsVisibility() {
    // No-op: ± and SHOW/HIDE buttons are rendered inside the dynamic PV HTML.
}

function stockfishPNACLModuleDidLoad() {
    window.StockfishModule = document.getElementById('stockfish_module');
    window.StockfishModule.postMessage('uci');
}

function handleCrash(event) {
    console.warn('Nacl Module crash handler method');
    console.warn(event);
    loadNaclStockfish();
}

function handleMessage(event) {
    if (!event || !event.data) return;
    var output = formatEngineOutput(event.data);
    if (output && output.pv_index === 1) {
        // Update the static SF18 first-PV row
        var metaEl = document.getElementById('sf18Meta');
        var bodyEl = document.getElementById('sf18Pv1Body');
        if (metaEl) metaEl.innerHTML = output.meta || '';
        if (bodyEl) bodyEl.innerHTML = output.body || '';
    } else if (output && output.pv_index > 1) {
        $('#pv_' + output.pv_index).html(output.line);
    }
        var multiPvStatusEl = $('#engineMultiPVStatus');
        if (multiPvStatusEl.length) {
            multiPvStatusEl.html(window.multipv + (window.multipv > 1 ? ' lines' : ' line'));
        }
}

function loadNaclStockfish() {
    var listener = document.getElementById('listener');
    listener.addEventListener('load', stockfishPNACLModuleDidLoad, true);
    listener.addEventListener('message', function (event) {
        if (event && event.data) {
            handleMessage(event);
        }
    }, true);
    listener.addEventListener('crash', handleCrash, true);
}

function stopAnalysis() {
    if (!window.StockfishModule) {
        if (window.stockfish) {
            window.stockfish.terminate();
            window.stockfish = null;
        }
    } else {
        try {
            window.StockfishModule.postMessage('stop');
        }
        catch (err) {
            console.warn(err);
        }
    }

    // Clear extra PV lines (pv_2+); pv_1 is now static HTML in sf18Row
    $('#pv_output').empty();
    for (var i = 2; i <= window.multipv; i++) {
        $('#pv_output').append('<div id="pv_' + i + '" class="pv-container"></div>');
    }

    // Ocultar la barra de evaluación cuando se detiene el análisis
    if (!window.analysis) {
        $('#evaluationBar').css('visibility', 'hidden');
    }
}

function getCountPrevMoves(node) {
    if (node.previous) {
        return getCountPrevMoves(node.previous) + 1;
    } else {
        return 0;
    }
}

function getPreviousMoves(node, format) {
    format = format || 'raw';

    if (node.previous) {
        var san = '';
        if (format === 'san') {
            if (node.half_move_num % 2 === 1) {
                san += Math.floor((node.half_move_num + 1) / 2) + ". "
            }
            san += node.move.san;
        }
        else {
            san += node.move.from + node.move.to + (node.move.promotion ? node.move.promotion : '');
        }
        return getPreviousMoves(node.previous, format) + ' ' + san;
    } else {
        return '';
    }
}

function analyze(position_update) {
    if (isLocalWebClient()) {
        window.multipv = 1;
    }

    if (!position_update) {
        if (!window.analysis) {
            window.analysis = true;
            var sf18Btn = document.getElementById('sf18ToggleBtn');
            if (sf18Btn) sf18Btn.textContent = 'HIDE';
            updateSF18PmButtons();
        }
        else {
            window.analysis = false;
            setSF18Placeholder();
            stopAnalysis();
            $('#engineStatus').html('');
            $('#evaluationBar').css('visibility', 'hidden');
            return;
        }
    }
    var moves;
    if (currentPosition === undefined) {
        moves = '';
    }
    else {
        moves = getPreviousMoves(currentPosition);
    }
    if (!window.StockfishModule) {
        if (!window.stockfish) {
            window.stockfish = new Worker('/static/js/stockfish.js');
            window.stockfish.onmessage = function (event) {
                if (event && event.data) {
                    handleMessage(event);
                }
            };
        }
    }
    else if (!window.stockfish) {
        window.stockfish = StockfishModule;
    }

    var startpos = 'startpos';
    if (setupBoardFen !== START_FEN) {
        startpos = 'fen ' + setupBoardFen;
    }
    if (position_update && window.stockfish) {
        window.stockfish.postMessage('stop');
    }
    window.stockfish.postMessage('position ' + startpos + ' moves ' + moves);
    window.stockfish.postMessage('setoption name multipv value ' + window.multipv);
    window.stockfish.postMessage('go infinite');
}

function updateDGTPosition(data) {
    if (data.play === 'reload') {
        // Takeback / switch-sides: always rebuild the move tree from the
        // fresh PGN so the diagram and move list are in sync, even when
        // the target FEN already exists in the current fenHash (i.e. a
        // real move takeback where the previous position is in the list).
        loadGame(data['pgn'].split("\n"));
        if (!goToPosition(data.fen)) {
            // Variant chess or edge-cases: force the board to the server FEN.
            forcePosition(data.fen);
        }
        return;
    }
    if (!goToPosition(data.fen)) {
        loadGame(data['pgn'].split("\n"));
        if (!goToPosition(data.fen)) {
            // Variant chess (e.g. atomic explosions): chess.js computed a different
            // FEN than the server sent.  Force the board to show the server's FEN.
            forcePosition(data.fen);
        }
    }
}

function forcePosition(fen) {
    // For variant chess (e.g. atomic) the server sends the correct FEN but
    // chess.js has no variant support and computes a standard-rules FEN.
    // Use the last known game node for move metadata and override the display.
    if (fenHash['last']) {
        currentPosition = fenHash['last'];
        // Override the chess.js-computed FEN with the server's correct FEN
        // so that subsequent Light events and goToPosition work correctly.
        var oldFen = currentPosition.fen;
        currentPosition.fen = fen;
        fenHash[fen] = currentPosition;
        if (oldFen && oldFen !== fen) {
            delete fenHash[oldFen];
        }
    } else {
        // No moves in the game (e.g. takeback to the starting position).
        // Use the root gameHistory node so updateChessGround() has a valid
        // currentPosition object with the correct FEN to display.
        currentPosition = gameHistory;
        if (currentPosition) {
            currentPosition.fen = fen;
            fenHash[fen] = currentPosition;
        }
    }
    updateChessGround();
    updateStatus();
}

function updateTutorMistakes(mistakes) {
    var listEl = document.getElementById('tutorMistakeList');
    if (!listEl) {
        return;
    }
    listEl.innerHTML = '';
    if (!Array.isArray(mistakes) || mistakes.length === 0) {
        var emptyItem = document.createElement('li');
        emptyItem.className = 'list-group-item text-muted';
        emptyItem.textContent = 'No tutor mistakes yet';
        listEl.appendChild(emptyItem);
        return;
    }
    mistakes.forEach(function (item) {
        var entry = document.createElement('li');
        entry.className = 'list-group-item tutor-mistake-item';
        var nag = item.nag ? item.nag : '';
        var figUser = figurinizeMove(item.user_move) || (item.user_move || '');
        var figBest = figurinizeMove(item.best_move) || (item.best_move || '');
        var moveText = (item.move_no ? item.move_no + ' ' : '') + figUser + nag;
        entry.innerHTML = moveText + ' \u2014 CPL: ' + item.cpl + ', best: ' + figBest;
        if (item.halfmove) {
            entry.dataset.halfmove = item.halfmove;
            entry.addEventListener('click', function () {
                goToHalfmove(entry.dataset.halfmove);
            });
        }
        listEl.appendChild(entry);
    });
    var container = listEl.parentElement;
    if (container) {
        container.scrollTop = container.scrollHeight;
    }
}

function findFenByHalfmove(halfmove) {
    if (!fenHash || !halfmove) {
        return null;
    }
    var target = parseInt(halfmove, 10);
    if (Number.isNaN(target) || target < 1) {
        return null;
    }
    for (var key in fenHash) {
        if (!Object.prototype.hasOwnProperty.call(fenHash, key)) {
            continue;
        }
        if (key === 'first' || key === 'last') {
            continue;
        }
        var node = fenHash[key];
        if (!node || typeof node !== 'object') {
            continue;
        }
        if (node.half_move_num === target) {
            return node.fen;
        }
    }
    return null;
}

function goToHalfmove(halfmove) {
    var fen = findFenByHalfmove(halfmove);
    if (!fen) {
        return false;
    }
    goToPosition(fen);
    removeHighlights();
    return true;
}

function getStartMoveNumFromFen(fen) {
    if (!fen) {
        return 1;
    }
    var parts = fen.split(' ');
    if (parts.length < 6) {
        return 1;
    }
    var turn = parts[1];
    var fullmove = parseInt(parts[5], 10);
    if (Number.isNaN(fullmove) || fullmove < 1) {
        return 1;
    }
    return ((fullmove - 1) * 2) + (turn === 'w' ? 1 : 2);
}

var MAX_BACKEND_PV_MOVES = 8;

function formatBackendAnalysisPv(pvMoves, baseFen) {
    if (!Array.isArray(pvMoves) || pvMoves.length === 0) {
        if (typeof pvMoves === 'string') {
            pvMoves = pvMoves.trim().split(/\s+/);
        } else {
            return null;
        }
    }

    var normalizedMoves = [];
    for (var i = 0; i < pvMoves.length; i++) {
        var rawMove = pvMoves[i];
        if (!rawMove) {
            continue;
        }
        if (typeof rawMove === 'string') {
            var cleaned = rawMove.trim();
            if (!cleaned) {
                continue;
            }
            var parts = cleaned.split(/\s+/);
            for (var j = 0; j < parts.length; j++) {
                if (parts[j]) {
                    normalizedMoves.push(parts[j]);
                }
            }
            continue;
        }
        if (rawMove.from && rawMove.to) {
            var promotion = rawMove.promotion ? String(rawMove.promotion) : '';
            normalizedMoves.push(rawMove.from + rawMove.to + promotion);
        }
    }
    if (normalizedMoves.length === 0) {
        return null;
    }

    // Detect whether moves are pre-computed SAN (sent by Python) or raw UCI.
    // UCI moves match exactly: [a-h][1-8][a-h][1-8] with optional promotion letter.
    // SAN moves (e4, Nf3, O-O, Qxd5+, e8=Q, etc.) do NOT match this pattern.
    // Python converts to SAN before sending; UCI is only a fallback when that fails.
    var uciPattern = /^[a-h][1-8][a-h][1-8][qrbn]?$/i;
    var movesAreSan = !uciPattern.test(normalizedMoves[0]);

    // Load the position FEN to determine turn (w/b) and full-move number.
    // For SAN moves we only need this metadata; the moves themselves are already formatted.
    // For UCI moves we also need to apply them through chess.js to obtain SAN history.
    var startMoveNum = 1;
    var baseTurn = 'w';
    var fenForMeta = baseFen || (currentPosition && currentPosition.fen) || '';
    if (fenForMeta) {
        var metaGame = new Chess();
        if (metaGame.load(fenForMeta, chessGameType)) {
            startMoveNum = baseFen
                ? getStartMoveNumFromFen(baseFen)
                : (getCountPrevMoves(currentPosition) + 1);
            baseTurn = metaGame.turn();
        } else if (baseFen && currentPosition && currentPosition.fen) {
            var metaGame2 = new Chess();
            if (metaGame2.load(currentPosition.fen, chessGameType)) {
                startMoveNum = getCountPrevMoves(currentPosition) + 1;
                baseTurn = metaGame2.turn();
            }
        }
    }

    var formattedMoves;
    if (movesAreSan) {
        // Python pre-computed SAN: figurinize each string directly.
        // No chess.js move application needed — avoids FEN/move-application failures.
        formattedMoves = normalizedMoves.map(function (m) { return figurinizeMove(m); });
    } else {
        // Raw UCI fallback: apply moves through chess.js to obtain SAN, then figurinize.
        function applyBackendMove(game, moveText) {
            if (!moveText || typeof moveText !== 'string') { return null; }
            var c = moveText.trim();
            if (!c) { return null; }
            var uciMatch = c.match(/^([a-h][1-8])([a-h][1-8])([qrbn])?$/i);
            if (uciMatch) {
                var from = uciMatch[1], to = uciMatch[2];
                var promo = uciMatch[3] ? uciMatch[3].toLowerCase() : '';
                return promo ? game.move({ from: from, to: to, promotion: promo })
                             : game.move({ from: from, to: to });
            }
            return game.move(c, { sloppy: true });
        }

        var uciGame = new Chess();
        var loaded = false;
        if (baseFen && uciGame.load(baseFen, chessGameType)) {
            loaded = true;
        } else if (currentPosition && currentPosition.fen
                   && uciGame.load(currentPosition.fen, chessGameType)) {
            loaded = true;
        }
        if (!loaded) { return null; }

        for (var k = 0; k < normalizedMoves.length; k++) {
            if (!applyBackendMove(uciGame, normalizedMoves[k])) { break; }
        }
        var history = uciGame.history();
        if (history.length === 0) { return null; }
        formattedMoves = history.map(function (m) { return figurinizeMove(m); });
    }

    if (!formattedMoves || formattedMoves.length === 0) { return null; }

    var moveNumber = Math.floor((startMoveNum + 1) / 2);
    var firstMoveText = (baseTurn === 'w') ? moveNumber + '. ' : moveNumber + '... ';
    firstMoveText += formattedMoves[0];

    var continuationText = '';
    var currentMoveNum = startMoveNum;
    for (var n = 1; n < formattedMoves.length; n++) {
        currentMoveNum++;
        if (currentMoveNum % 2 === 1) {
            continuationText += Math.floor((currentMoveNum + 1) / 2) + '. ';
        }
        continuationText += formattedMoves[n] + ' ';
    }

    return {
        firstMove: firstMoveText,
        continuation: continuationText.trim()
    };
}

// Update the static engine-row elements with live analysis data.
function updateBackendAnalysisLine(analysis) {
    if (!analysis) {
        setEngineLinePlaceholder();
        return;
    }
    var scoreText = '?';
    if (analysis.mate) {
        scoreText = '#' + analysis.mate;
    } else if (analysis.score !== null && analysis.score !== undefined) {
        var numericScore = analysis.score / 100.0;
        scoreText = (numericScore > 0 ? '+' : '') + numericScore.toFixed(2);
    }
    var scoreClass = 'score-display';
    if (String(scoreText).includes('#')) {
        scoreClass += ' score-mate';
    } else if (scoreText !== '?' && parseFloat(scoreText) > 0) {
        scoreClass += ' score-positive';
    } else if (scoreText !== '?' && parseFloat(scoreText) < 0) {
        scoreClass += ' score-negative';
    }
    var pvMoves = Array.isArray(analysis.pv) ? analysis.pv.slice(0, MAX_BACKEND_PV_MOVES) : [];
    var pvFormatted = formatBackendAnalysisPv(pvMoves, analysis.fen);

    // Update score+depth in #engineMeta
    var metaEl = document.getElementById('engineMeta');
    if (metaEl) {
        var metaHtml = '<span class="' + scoreClass + '">' + scoreText + '</span>';
        if (typeof analysis.depth === 'number') {
            metaHtml += '<span class="depth-display">d' + analysis.depth + '</span>';
        }
        metaEl.innerHTML = metaHtml;
    }
    // Update PV moves in #enginePvBody
    var bodyEl = document.getElementById('enginePvBody');
    if (bodyEl) {
        var bodyHtml = '';
        if (pvFormatted) {
            bodyHtml += '<span class="first-move">' + pvFormatted.firstMove + '</span>';
            if (pvFormatted.continuation) {
                bodyHtml += '<span class="continuation-moves">' + pvFormatted.continuation + '</span>';
            }
        } else if (pvMoves.length > 0) {
            bodyHtml += '<span class="pv-display">' + pvMoves.join(' ') + '</span>';
        }
        bodyEl.innerHTML = bodyHtml;
    }
    // Button text: HIDE (analysis is showing)
    var btn = document.getElementById('engineToggleBtn');
    if (btn) btn.textContent = 'HIDE';
}

var analysisDisplayVisible = false;
var lastServerAnalysis = null;

// Ponder mode: real-time single-line display in #DGTClockText
// Format: "24. Qxe5+ d27 +2.34"  (all on one line, updated on every Analysis event)
var analysisClockData = null;

function isAnalysisClockMode(mode) {
    var resolvedMode = mode || (window._picoSystemInfo || {}).interaction_mode;
    return resolvedMode === 'ponder';
}

function _buildAnalysisClockLine(analysis) {
    var parts = [];
    var fen = analysis.fen || '';
    var pv  = Array.isArray(analysis.pv) ? analysis.pv : [];
    if (pv.length > 0) {
        var moveNum = 1;
        var isBlack = false;
        if (fen) {
            var fp = fen.split(/\s+/);
            if (fp.length >= 6) {
                var n = parseInt(fp[5], 10);
                if (!isNaN(n) && n >= 1) moveNum = n;
            }
            isBlack = (fp[1] === 'b');
        }
        var raw = typeof pv[0] === 'string' ? pv[0].trim() : '';
        var san = null;
        if (raw) {
            if (/^[a-h][1-8][a-h][1-8][qrbn]?$/i.test(raw)) {
                // UCI fallback — convert to SAN via chess.js
                if (fen) {
                    try {
                        var b = new Chess(fen, chessGameType);
                        var mv = b.move({ from: raw.slice(0, 2), to: raw.slice(2, 4),
                                          promotion: raw[4] || undefined });
                        if (mv) san = mv.san;
                    } catch (e) {}
                }
                if (!san) san = raw;  // keep raw UCI if conversion fails
            } else {
                san = raw;  // already SAN (pre-converted by backend)
            }
        }
        if (san) {
            // "24. Nc4" for white, "24...Nc4" for black
            parts.push(isBlack ? moveNum + '...' + san : moveNum + '. ' + san);
        }
    }
    if (typeof analysis.depth === 'number') {
        parts.push('d' + analysis.depth);
    }
    if (analysis.mate) {
        parts.push('#' + analysis.mate);
    } else if (analysis.score !== null && analysis.score !== undefined) {
        var s = analysis.score / 100.0;
        parts.push((s > 0 ? '+' : '') + s.toFixed(2));
    }
    return parts.join(' ');
}

function stopAnalysisClock() {
    analysisClockData = null;
    // Do NOT clear dgtClockTextEl here — that would wipe Normal-mode clock
    // times when called from ws.onopen or case 'Game'.  Clearing is done
    // explicitly in the SystemInfo handler on Analysis-mode entry only.
}

function updateAnalysisClock(analysis) {
    if (!analysis || analysis.clear) { stopAnalysisClock(); return; }
    analysisClockData = analysis;
    if (!isAnalysisClockMode()) return;
    var line = _buildAnalysisClockLine(analysis);
    if (line) dgtClockTextEl.html(line);
}

// Clear engine analysis content; reset button to SHOW.
function setEngineLinePlaceholder() {
    var metaEl = document.getElementById('engineMeta');
    var bodyEl = document.getElementById('enginePvBody');
    var btn    = document.getElementById('engineToggleBtn');
    if (metaEl) metaEl.innerHTML = '';
    if (bodyEl) bodyEl.innerHTML = '';
    if (btn)    btn.textContent = 'SHOW';
}

// Update ± button visibility and disabled state based on SF18 running state and multipv count.
function updateSF18PmButtons() {
    var group    = document.getElementById('sf18PmGroup');
    var minusBtn = document.getElementById('analyzeMinus');
    var plusBtn  = document.getElementById('analyzePlus');
    if (!group) return;
    if (!window.analysis || isLocalWebClient()) {
        $(group).hide();
    } else {
        $(group).show();
        if (minusBtn) minusBtn.disabled = (window.multipv <= 1);
        if (plusBtn) plusBtn.disabled = false;
    }
}

// Clear SF18 first-PV content; reset button to SHOW.
function setSF18Placeholder() {
    var metaEl = document.getElementById('sf18Meta');
    var bodyEl = document.getElementById('sf18Pv1Body');
    var btn    = document.getElementById('sf18ToggleBtn');
    if (metaEl) metaEl.innerHTML = '';
    if (bodyEl) bodyEl.innerHTML = '';
    if (btn)    btn.textContent = 'SHOW';
    // Clear extra PV lines
    $('#pv_output').empty();
    updateSF18PmButtons();
}

function updateBackendAnalysis(analysis) {
    if (!analysis) {
        lastServerAnalysis = null;
        // Clear content but keep button state
        var metaEl = document.getElementById('engineMeta');
        var bodyEl = document.getElementById('enginePvBody');
        if (metaEl) metaEl.innerHTML = '';
        if (bodyEl) bodyEl.innerHTML = '';
        return;
    }
    // Upstream: explicit clear signal resets the engine line to placeholder state.
    if (analysis.clear) {
        setEngineLinePlaceholder();
        return;
    }
    lastServerAnalysis = analysis;
    if (!analysisDisplayVisible) {
        return;
    }
    updateBackendAnalysisLine(analysis);
}

function goToDGTFen() {
    $.get('/dgt', { action: 'get_last_move' }, function (data) {
        if (data && data.fen) {
            if (data.play === 'newgame') {
                // Server is at a fresh game — reset board and move list together,
                // same as the 'Game' WebSocket event handler does.
                var savedHeader = gameHistory.gameHeader || '';
                newBoard(data.fen);
                gameHistory.gameHeader = savedHeader;
                writeVariationTree(pgnEl, '', gameHistory);
                removeHighlights();
                removeArrow();
            } else {
                updateDGTPosition(data);
                if (window.chessground1) { window.chessground1.redrawAll(); }
                highlightBoard(data.move, data.play);
                addArrow(data.move, data.play);
                updateTutorMistakes(data.mistakes);
            }
        } else {
            // No active game: show starting position
            newBoard(START_FEN);
            removeHighlights();
            removeArrow();
        }
    }).fail(function (jqXHR, textStatus) {
        dgtClockStatusEl.html(textStatus);
    });
}

function setTitle(data) {
    window.ip_info = data;
    var ip = '';
    if (window.ip_info.ext_ip) {
        ip += ' IP: ' + window.ip_info.ext_ip;
    }
    var version = '';
    if (window.ip_info.version) {
        version = window.ip_info.version;
    } else if (window.system_info.version) {
        version = window.system_info.version;
    }
    document.title = 'Webserver Picochess ' + version + ip;
}

// copied from loadGame()
function setHeaders(data) {
    // Validar que data sea un objeto válido
    if (!data || typeof data !== 'object') {
        console.debug('setHeaders: data is not a valid object', data);
        return;
    }

    if ('FEN' in data && 'SetUp' in data) {
        if ('Variant' in data && 'Chess960' === data['Variant']) {
            chessGameType = 1; // values from chess960.js
        } else {
            chessGameType = 0;
        }
    }
    gameHistory.gameHeader = getWebGameHeader(data);
    gameHistory.result = data.Result;
    gameHistory.originalHeader = data;
    var exporter = new WebExporter();
    exportGame(gameHistory, exporter, true, true, undefined, false);
    writeVariationTree(pgnEl, exporter.toString(), gameHistory);
}

function getAllInfo() {
    $.get('/info', { action: 'get_system_info' }, function (data) {
        window.system_info = data;
        // Merge into _picoSystemInfo (used by the overlay) and refresh diagram
        // interactivity — in particular the has_board flag locks the diagram
        // when a physical board is the source of truth for piece positions.
        window._picoSystemInfo = window._picoSystemInfo || {};
        Object.assign(window._picoSystemInfo, data);
        if (Object.prototype.hasOwnProperty.call(data, 'game_started') && window.setPicoGameActive) {
            window.setPicoGameActive(Boolean(data.game_started));
        }
        if (window.setTutorSettings && Object.prototype.hasOwnProperty.call(data, 'tutor_watcher')) {
            window.setTutorSettings(data);
        }
        if (window.chessground1) { updateChessGround(); }
        if (window.syncClockControls) { window.syncClockControls(); }
    }).fail(function (jqXHR, textStatus) {
        dgtClockStatusEl.html(textStatus);
    });
    $.get('/info', { action: 'get_ip_info' }, function (data) {
        setTitle(data);
    }).fail(function (jqXHR, textStatus) {
        dgtClockStatusEl.html(textStatus);
    });
    $.get('/info', { action: 'get_headers' }, function (data) {
        setHeaders(data);
    }).fail(function (jqXHR, textStatus) {
        dgtClockStatusEl.html(textStatus);
    });
    $.get('/info', { action: 'get_clock_text' }, function (data) {
        dgtClockTextEl.html(data);
        $.get('/info', { action: 'get_clock_state' }, function (state) {
            if (window.syncClockControls) {
                window.syncClockControls(Boolean(state && state.running));
            }
        }).fail(function () {});
    }).fail(function (jqXHR, textStatus) {
        console.warn(textStatus);
        dgtClockStatusEl.html(textStatus);
    });
}

var boardThemes = ['blue', 'green', 'metal', 'natural-wood', 'newspaper', 'soft', 'wood'];
var pieceSets = ['alpha', 'berlin', 'leipzig', 'merida', 'uscf'];

function getCurrentBoardTheme() {
    var section = $('#xboardsection');
    for (var i = 0; i < boardThemes.length; i++) {
        if (section.hasClass(boardThemes[i])) {
            return i;
        }
    }
    return boardThemes.indexOf('natural-wood');
}

function changeBoardTheme() {
    var currentIndex = getCurrentBoardTheme();
    var newIndex = (currentIndex + 1) % boardThemes.length;
    var theme = boardThemes[newIndex];

    $('#xboardsection').removeClass(boardThemes.join(' '));
    $('#xboardsection').addClass(theme);

    var themeLink = $('#theme-' + theme);
    if (themeLink.length === 0) {
        $('head').append('<link id="theme-' + theme + '" rel="stylesheet" href="/static/css/chessground/theme_' + theme.replace('-', '_') + '.css" />');
    }

    // Persist to server so the choice survives page reloads
    var boardValue = theme.replace(/-/g, '_');
    $.ajax({
        url: '/settings/save',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({entries: [{key: 'web-board-theme', value: boardValue, enabled: true}]})
    });
}

function loadSavedTheme() {
    // Board theme is rendered server-side from picochess.ini — no client-side override needed
}

function getCurrentPieceSet() {
    var section = $('#xboardsection');
    for (var i = 0; i < pieceSets.length; i++) {
        if (section.hasClass(pieceSets[i])) {
            return i;
        }
    }
    return pieceSets.indexOf('merida');
}

function syncKingBadgeIcons() {
    var pieces = pieceSets.find(function(p) { return $('#xboardsection').hasClass(p); }) || 'merida';
    var base = '/static/css/chessground/images/pieces/' + pieces + '/';
    var wImg = document.getElementById('checkKingW');
    var bImg = document.getElementById('checkKingB');
    if (wImg) wImg.src = base + 'wK.svg';
    if (bImg) bImg.src = base + 'bK.svg';
}

function changePieceSet() {
    var currentIndex = getCurrentPieceSet();
    var newIndex = (currentIndex + 1) % pieceSets.length;
    var pieces = pieceSets[newIndex];

    $('#xboardsection').removeClass(pieceSets.join(' '));
    $('#xboardsection').addClass(pieces);
    syncKingBadgeIcons();

    // Persist to server so the choice survives page reloads
    $.ajax({
        url: '/settings/save',
        type: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({entries: [{key: 'pieces', value: pieces, enabled: true}]})
    });
}

$('#flipOrientationBtn').on('click', boardFlip);
$('#DgtSyncBtn').on('click', goToDGTFen);
$('#colorBtn').on('click', changeBoardTheme);
$('#piecesBtn').on('click', changePieceSet);
$('#backBtn').on('click', goBack);
$('#fwdBtn').on('click', goForward);
$('#startBtn').on('click', goToStart);
$('#endBtn').on('click', goToEnd);

$(window).on('load', function () {
    updateWebAudioMuteButtonVisibility();
    $('#downloadBtn').on('click', download);
    $('#uploadBtn').on('click', function () {
        window.location.href = 'upload';
    });
});

$('#ClockBtn0').on('click', clockButton0);
$('#ClockBtn1').on('click', clockButton1);
$('#ClockBtn2').on('click', clockButton2);
$('#ClockBtn3').on('click', clockButton3);
$('#ClockBtn4').on('click', clockButton4);
$('#ClockLeverBtn').on('click', toggleLeverButton);
$('#clockSwitchSidesBtn').on('click', clockSwitchSides);
$('#clockPauseResumeBtn').on('click', clockPauseResume);
$('#clockEvalBtn').on('click', clockShowEvaluation);
$('#clockHintBtn').on('click', clockShowHint);

$("#ClockBtn0").mouseup(function () {
    btn = $(this);
    setTimeout(function () { btn.blur(); }, 100);
})
$("#ClockBtn1").mouseup(function () {
    btn = $(this);
    setTimeout(function () { btn.blur(); }, 100);
})
$("#ClockBtn2").mouseup(function () {
    btn = $(this);
    setTimeout(function () { btn.blur(); }, 100);
})
$("#ClockBtn3").mouseup(function () {
    btn = $(this);
    setTimeout(function () { btn.blur(); }, 100);
})
$("#ClockBtn4").mouseup(function () {
    btn = $(this);
    setTimeout(function () { btn.blur(); }, 100);
})
$("#ClockLeverBtn").mouseup(function () {
    btn = $(this);
    setTimeout(function () { btn.blur(); }, 100);
})
$("#clockEvalBtn, #clockSwitchSidesBtn, #clockPauseResumeBtn, #clockHintBtn").mouseup(function () {
    var btn = $(this);
    setTimeout(function () { btn.blur(); }, 100);
})

$(function () {
    loadSavedTheme();
    getAllInfo();
    loadWebBookList();
    // Render placeholders immediately on page load before any analysis arrives.
    setEngineLinePlaceholder();
    setSF18Placeholder();

    $('a[data-toggle="tab"]').on('shown.bs.tab', function (e) {
        updateStatus();
        var target = $(e.target).attr('data-bs-target') || $(e.target).attr('href');
        if (target === '#book') {
            loadWebBookList();
            bookDataTable.ajax.reload();
        } else if (target === '#games') {
            gameDataTable.ajax.reload();
        }
    });
    window.engine_lines = {};
    window.multipv = 1;

    $(document).keydown(function (e) {
        if (e.keyCode === 39) { // right arrow
            if (e.ctrlKey) {
                $('#endBtn').click();
            } else {
                $('#fwdBtn').click();
            }
            return true;
        }
    });

    $(document).keydown(function (e) {
        if (e.keyCode === 37) { // left arrow
            if (e.ctrlKey) {
                $('#startBtn').click();
            } else {
                $('#backBtn').click();
            }
        }
        return true;
    });
    updateStatus();

    window.WebSocket = window.WebSocket || window.MozWebSocket || false;
    if (!window.WebSocket) {
        alert('No WebSocket Support');
    }
    else {
        // WebSocket with automatic reconnect.
        // The server syncs board state and last analysis on every new
        // connection (server.py EventHandler.open), so reconnecting
        // restores the analysis display without any extra client logic.
        var wsReconnectDelay = 2000; // start at 2 s, doubles each attempt
        var wsReconnectTimer = null;

        function connectWebSocket() {
            var ws = new WebSocket('ws://' + location.host + '/event');

            ws.onopen = function () {
                // Reset backoff on successful connection.
                wsReconnectDelay = 2000;
                stopAnalysisClock();
                // Ensure placeholders are visible while waiting for first messages.
                setEngineLinePlaceholder();
                if (!window.analysis) setSF18Placeholder();
            };

            // Process messages from picochess
            ws.onmessage = function (e) {
                var data = JSON.parse(e.data);
                switch (data.event) {
                    case 'Fen':
                        pickPromotion(null) // reset promotion dialog if still showing
                        updateDGTPosition(data);
                        updateTutorMistakes(data.mistakes);
                        updateCheckCounters(data.variant, data.checks);
                        if (data.play === 'reload') {
                            removeHighlights();
                            // Force a full chessground redraw so the diagram
                            // always reflects the post-takeback position, even
                            // when the FEN was already present in the move list
                            // (the board render can otherwise be deferred/stale).
                            if (window.chessground1) { window.chessground1.redrawAll(); }
                        }
                        if (data.play === 'user') {
                            highlightBoard(data.move, 'user');
                            if (window.setPicoGameActive) window.setPicoGameActive(true);
                            if (window.setPicoEngineTurn) window.setPicoEngineTurn(false);
                        }
                        if (data.play === 'computer') {
                            if (window.setPicoGameActive) window.setPicoGameActive(true);
                            if (window.setPicoEngineTurn) window.setPicoEngineTurn(true);
                        }
                        if (data.play === 'review') {
                            highlightBoard(data.move, 'review');
                        }
                        break;
                    case 'Game':
                        stopAnalysisClock();
                        var savedGameHeader = gameHistory.gameHeader || '';
                        newBoard(data.fen);
                        gameHistory.gameHeader = savedGameHeader;
                        // Clear the move list — newBoard() resets the game tree but
                        // does not update the DOM, leaving the previous game's moves visible.
                        writeVariationTree(pgnEl, '', gameHistory);
                        updateTutorMistakes(data.mistakes);
                        updateCheckCounters(data.variant, data.checks);
                        // New board = no moves played yet
                        if (window.setPicoGameActive) window.setPicoGameActive(false);
                        if (window.setPicoEngineTurn) window.setPicoEngineTurn(false);
                        break;
                    case 'Analysis':
                        updateBackendAnalysis(data.analysis);
                        updateAnalysisClock(data.analysis);
                        break;
                    case 'Message':
                        boardStatusEl.html(data.msg);
                        break;
                    case 'Clock':
                        if (!isAnalysisClockMode()) {
                            dgtClockTextEl.html(data.msg);
                        }
                        if (window.syncClockControls) {
                            if (Object.prototype.hasOwnProperty.call(data, 'running')) {
                                window.syncClockControls(Boolean(data.running));
                            } else {
                                window.syncClockControls();
                            }
                        }
                        break;
                    case 'WebAudio':
                        queueBackendAudio(data.audio);
                        break;
                    case 'Status':
                        var dgtEl = document.getElementById('picoFooterDgt');
                        if (dgtEl) {
                            if (data.eboard === 'connected') {
                                dgtEl.classList.add('footer-connected');
                            } else if (data.eboard === 'error' || data.eboard === 'noeboard') {
                                dgtEl.classList.remove('footer-connected');
                            }
                        }
                        break;
                    case 'TutorWatch':
                        if (data.settings && window.setTutorSettings) {
                            window.setTutorSettings(data.settings);
                        } else if (window.setTutorWatchState) {
                            window.setTutorWatchState(Boolean(data.active));
                        }
                        break;
                    case 'TutorSettings':
                        if (window.setTutorSettings) {
                            window.setTutorSettings(data.settings || data);
                        }
                        break;
                    case 'Light':
                        var tmp_board = new Chess(currentPosition.fen, chessGameType);
                        var tmp_move = tmp_board.move(data.move, { sloppy: true });
                        if (tmp_move !== null) {
                            computerside = tmp_move.color;
                            saymove(tmp_move, tmp_board);
                        }
                        // Always show highlight and arrow for computer moves,
                        // even when chess.js can't validate the move (atomic variant).
                        highlightBoard(data.move, 'computer');
                        addArrow(data.move, 'computer');
                        break;
                    case 'Clear':
                        break;
                    case 'Header':
                        setHeaders(data['headers']);
                        // Definitive result means game ended
                        if (window.setPicoGameActive) {
                            var _res = data['headers'] && data['headers']['Result'];
                            if (_res === '1-0' || _res === '0-1' || _res === '1/2-1/2') {
                                window.setPicoGameActive(false);
                            }
                        }
                        break;
                    case 'Title':
                        setTitle(data['ip_info']);
                        break;
                    case 'Broadcast':
                        boardStatusEl.html(data.msg);
                        break;
                    case 'PromotionDlg':
                        // for e-boards that do not feature piece recognition
                        promotionDialog(data.move);
                        break;
                    case 'SystemInfo':
                        // Live update of interaction_mode / play_mode so the
                        // diagram immediately locks/unlocks when mode changes.
                        window._picoSystemInfo = window._picoSystemInfo || {};
                        var _prevMode = window._picoSystemInfo.interaction_mode;
                        Object.assign(window._picoSystemInfo, data.msg);
                        // Clear stale clock text (e.g. engine name) the moment we
                        // enter Ponder/free-analysis mode, before the first Analysis event arrives.
                        if (isAnalysisClockMode(data.msg.interaction_mode) && !isAnalysisClockMode(_prevMode)) {
                            stopAnalysisClock();
                            dgtClockTextEl.html('');
                        }
                        if (Object.prototype.hasOwnProperty.call(data.msg, 'game_started') && window.setPicoGameActive) {
                            window.setPicoGameActive(Boolean(data.msg.game_started));
                        }
                        if (Object.prototype.hasOwnProperty.call(data.msg, 'web_audio_backend_remote')) {
                            if (window.setPicoPhoneSpeaker) {
                                window.setPicoPhoneSpeaker(Boolean(data.msg.web_audio_backend_remote));
                            } else {
                                applyWebAudioBackendRemote(Boolean(data.msg.web_audio_backend_remote));
                            }
                        }
                        if (window.setTutorSettings && Object.prototype.hasOwnProperty.call(data.msg, 'tutor_watcher')) {
                            window.setTutorSettings(data.msg);
                        }
                        if (window.chessground1) { updateChessGround(); }
                        if (window.syncClockControls) { window.syncClockControls(); }
                        break;
                    default:
                        console.warn(data);
                }
            };

            ws.onclose = function () {
                dgtClockStatusEl.html('connecting…');
                // Stop client-side web analysis (in-browser Stockfish).
                // Server-side analysis display is preserved; the server will
                // re-send the cached analysis payload on reconnect.
                if (window.analysis || window.stockfish) {
                    window.analysis = false;
                    setSF18Placeholder();
                    stopAnalysis();
                    $('#engineStatus').html('');
                }
                // Schedule reconnect with exponential backoff (max 30 s).
                if (wsReconnectTimer) clearTimeout(wsReconnectTimer);
                wsReconnectTimer = setTimeout(function () {
                    wsReconnectTimer = null;
                    connectWebSocket();
                }, wsReconnectDelay);
                wsReconnectDelay = Math.min(wsReconnectDelay * 2, 30000);
            };

            ws.onerror = function (e) {
                // Log WS errors; onclose will fire afterward and handle reconnect.
                console.warn('WebSocket error', e);
            };
        }

        connectWebSocket();
    }

    if (navigator.mimeTypes['application/x-pnacl'] !== undefined) {
        loadNaclStockfish();
    }

    $.fn.dataTable.ext.errMode = 'throw';

    $('#bookPrev').on('click', function () { changeWebBook(-1); });
    $('#bookNext').on('click', function () { changeWebBook(1); });

    // Static bindings for persistent SHOW/HIDE and ± buttons.
    $('#engineToggleBtn').on('click', function () {
        if (analysisDisplayVisible) {
            analysisDisplayVisible = false;
            setEngineLinePlaceholder();
        } else {
            analysisDisplayVisible = true;
            if (lastServerAnalysis) {
                updateBackendAnalysisLine(lastServerAnalysis);
            } else {
                // No data yet — show HIDE so user knows it's active
                var btn = document.getElementById('engineToggleBtn');
                if (btn) btn.textContent = 'HIDE';
            }
        }
    });
    $('#sf18ToggleBtn').on('click', analyzePressed);

    $('#analyzeMinus').on('click', multiPvDecrease);
    $('#analyzePlus').on('click', multiPvIncrease);
});

// promotion code taken from https://github.com/thinktt/chessg
function isPromotion(squareState, toSquare) {
    if (squareState.type !== 'p') return false
    if (toSquare.includes('8') || toSquare.includes('1')) return true
    return false
}

function html() {
    arguments[0] = { raw: arguments[0] };
    return String.raw(...arguments);
}

let setPromotion = null
async function getUserPromotion(toSquare) {
    const column = toSquare[0]
    const offSetMap = {
        'a': 0,
        'b': 12.5,
        'c': 25,
        'd': 37.5,
        'e': 50,
        'f': 62.5,
        'g': 75,
        'h': 87.5,
    }
    const leftOffset = offSetMap[column]

    let color = 'black'
    let queenTop = 87.5
    let topOffsetIncrement = -12.5

    if (toSquare.includes('8')) {
        color = 'white'
        queenTop = 0
        topOffsetIncrement = 12.5
    }

    const knightTop = queenTop + topOffsetIncrement
    const roookTop = knightTop + topOffsetIncrement
    const bishopTop = roookTop + topOffsetIncrement

    const promoChoiceHtml = html`
    <div class="promotion-overlay cg-wrap">
    <square onclick="pickPromotion('q')" style="top:${queenTop}%; left: ${leftOffset}%">
        <piece class="queen ${color}"></piece>
    </square>
    <square onclick="pickPromotion('n')" style="top:${knightTop}%; left: ${leftOffset}%">
        <piece class="knight ${color}"></piece>
    </square>
    <square onclick="pickPromotion('r')" style="top:${roookTop}%; left: ${leftOffset}%">
        <piece class="rook ${color}"></piece>
    </square>
    <square onclick="pickPromotion('b')" style="top:${bishopTop}%; left: ${leftOffset}%">
        <piece class="piece bishop ${color}"></piece>
    </square>
    </div>
    `

    const boardContainerEl = document.querySelector('.board-container')
    boardContainerEl.insertAdjacentHTML('beforeend', promoChoiceHtml)

    const piece = await new Promise(resolve => setPromotion = resolve)

    boardContainerEl.removeChild(document.querySelector('.promotion-overlay'))
    return piece
}

function pickPromotion(piece) {
    if (setPromotion) setPromotion(piece)
}

window.pickPromotion = pickPromotion
