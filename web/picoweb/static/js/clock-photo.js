'use strict';

function bindClockPhotoRocker(clock, sendButton) {
    const rocker = clock.querySelector('#photo-rocker');
    const artwork = clock.querySelector('.clock-rocker-artwork');
    let pending = false;

    rocker.addEventListener('click', async () => {
        if (pending) return;

        const previousSide = artwork.dataset.rockerDown;
        const rightDown = previousSide === 'left';
        pending = true;
        artwork.dataset.rockerDown = rightDown ? 'right' : 'left';
        if (!await sendButton(rightDown ? '64' : '-64')) artwork.dataset.rockerDown = previousSide;
        pending = false;
    });
}

function renderClockPhotoLCD(clockText) {
    const times = clockText.querySelectorAll('.ctime-l, .ctime-r');
    clockText.classList.toggle('lcd-times', times.length === 2);

    // The clock still sends its usual text and HTML. Draw numeric times as LCD
    // segments and leave moves, menu entries and other messages readable as text.
    const segments = {
        a: 'M8 1H33L38 6L33 11H8L3 6Z',
        b: 'M39 7L44 12V31L39 36L34 31V12Z',
        c: 'M39 38L44 43V62L39 67L34 62V43Z',
        d: 'M8 63H33L38 68L33 73H8L3 68Z',
        e: 'M3 38L8 43V62L3 67L-2 62V43Z',
        f: 'M3 7L8 12V31L3 36L-2 31V12Z',
        g: 'M9 32H33L38 37L33 42H9L4 37Z'
    };
    const digits = [
        'abcdef', 'bc', 'abdeg', 'abcdg', 'bcfg',
        'acdfg', 'acdefg', 'abc', 'abcdefg', 'abcdfg'
    ];
    const svgNamespace = 'http://www.w3.org/2000/svg';

    times.forEach((time) => {
        const value = time.textContent.trim();
        if (!/^\d+:\d{2}\.\d{2}$/.test(value)) return;

        const svg = document.createElementNS(svgNamespace, 'svg');
        svg.setAttribute('class', 'lcd-digits');
        svg.setAttribute('role', 'img');
        svg.setAttribute('aria-label', value);
        let offset = 0;
        for (const char of value) {
            const shape = document.createElementNS(svgNamespace, 'path');
            shape.setAttribute('transform', `translate(${offset + 11} 0) skewX(-8)`);
            if (char === ':' || char === '.') {
                shape.setAttribute('d', char === ':' ? 'M0 22H9V31H0Z M0 52H9V61H0Z' : 'M0 64H9V73H0Z');
                offset += 17;
            } else {
                shape.setAttribute('d', Array.from(digits[Number(char)], (segment) => segments[segment]).join(' '));
                offset += 49;
            }
            svg.appendChild(shape);
        }
        svg.setAttribute('viewBox', `0 0 ${offset + 8} 74`);
        time.replaceChildren(svg);
    });
}
