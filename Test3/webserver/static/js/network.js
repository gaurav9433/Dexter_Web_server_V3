
// e-sim

function toggleEsim() {
    const esimToggle = document.getElementById('esimToggle');
    const networkSelect = document.getElementById('networkSelect');
    const status = document.getElementById('status');

    if (esimToggle.checked) {
        networkSelect.disabled = false;
        status.textContent = 'e-SIM is enabled. Please select a network.';
        status.style.color = '#0066cc';
    } else {
        networkSelect.disabled = true;
        networkSelect.value = '';
        status.textContent = 'e-SIM is disabled';
        status.style.color = '#cc0000';
    }
}

function updateNetworkStatus() {
    const networkSelect = document.getElementById('networkSelect');
    const status = document.getElementById('status');
    
    if (networkSelect.value) {
        status.textContent = `Connected to ${networkSelect.options[networkSelect.selectedIndex].text}`;
        status.style.color = '#28a745';
    } else {
        status.textContent = 'SIM is enabled. Please select a network.';
        status.style.color = '#0066cc';
    }
}


// gnss

const gnssToggle = document.getElementById('gnssToggle');
const status = document.getElementById('status');

gnssToggle.addEventListener('change', () => {
    if (gnssToggle.checked) {
        status.textContent = 'GNSS is Enabled';
        console.log('GNSS Enabled');
        status.style.color = '#28a745';
        
        // Add your GNSS enabling code here
    } else {
        status.textContent = 'GNSS is Disabled';
        console.log('GNSS Disabled');
        status.style.color = '#0066cc';
        // Add your GNSS disabling code here
    }
});






// lan
function networkTest() {
    var networkStatus = document.getElementById('network-status');
    networkStatus.textContent = 'TESTING...';

    setTimeout(() => {
        networkStatus.textContent = 'CONNECTED';
    }, 3000); // Simulate a network test delay
}

function saveConfiguration() {
    alert('Configuration saved successfully!');
}

// gsm

    function gsm_on()
{
    if (gsmToggle.checked) {
        status.textContent = 'GSM is Enabled';
        status.style.color = '#28a745';
    } else {
        status.textContent = 'GSM is Disabled';
        status.style.color = '#0066cc';
    }
}
