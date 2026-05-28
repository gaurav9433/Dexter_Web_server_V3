document.addEventListener('DOMContentLoaded', () => {
    const switches = document.querySelectorAll('.switch');

    switches.forEach(switchElement => {
        switchElement.addEventListener('click', () => {
            startProgress(switchElement);
        });
    });

    function startProgress(switchElement) {
        const progressContainer = document.createElement('div');
        progressContainer.classList.add('progress-container');

        const progressBar = document.createElement('div');
        progressBar.classList.add('progress-bar');
        progressContainer.appendChild(progressBar);

        switchElement.replaceWith(progressContainer);

        // Start the progress bar animation
        setTimeout(() => {
            progressBar.style.transition = 'width 10s linear';
            progressBar.style.width = '100%';
        }, 100); // Slight delay to ensure the CSS transition works

        setTimeout(() => {
            const completeMessage = document.createElement('div');
            completeMessage.classList.add('complete-message');
            completeMessage.textContent = 'Done';
            completeMessage.addEventListener('click', () => {
                restoreSwitch(completeMessage, switchElement.id);
            });
            progressContainer.replaceWith(completeMessage);
        }, 10100); // 10 seconds + 100ms delay
    }

    function restoreSwitch(completeMessage, switchId) {
        const newSwitch = document.createElement('div');
        newSwitch.classList.add('switch');
        newSwitch.id = switchId;
        newSwitch.textContent = switchId.replace('switch', 'Switch ');
        newSwitch.addEventListener('click', () => {
            startProgress(newSwitch);
        });
        completeMessage.replaceWith(newSwitch);
    }
});
