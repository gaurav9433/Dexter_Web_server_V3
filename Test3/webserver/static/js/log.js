   document.addEventListener("DOMContentLoaded", function() {
    const logsBody = document.getElementById('logsBody');

    function fetchLogs() {
        fetch('http://localhost:3000/api/logs')
            .then(response => response.json())
            .then(data => {
                // Clear existing rows
                logsBody.innerHTML = '';

                const logs = data.logs;
                logs.forEach(log => {
                    const row = document.createElement('tr');

                    const zoneCell = document.createElement('td');
                    zoneCell.textContent = log.zone_number;
                    row.appendChild(zoneCell);

                    const deviceCell = document.createElement('td');
                    deviceCell.textContent = log.device_name;
                    row.appendChild(deviceCell);

                    const statusCell = document.createElement('td');
                    statusCell.textContent = log.status;
                    row.appendChild(statusCell);

                    const dataCell = document.createElement('td');
                    dataCell.textContent = log.data;
                    row.appendChild(dataCell);

                    const timeCell = document.createElement('td');
                    timeCell.textContent = log.time;
                    row.appendChild(timeCell);

                    logsBody.appendChild(row);
                });
            })
            .catch(error => {
                console.error('Error fetching logs:', error);
            });
    }   

        
        document.getElementById('downloadButton').addEventListener('click', function() {
    // Create a new workbook
    var wb = XLSX.utils.book_new();

    // Get the table element
    var table = document.getElementById('logsTable');

    // Convert the table to a worksheet
    var ws = XLSX.utils.table_to_sheet(table);

    // Append the worksheet to the workbook
    XLSX.utils.book_append_sheet(wb, ws, 'Logs');

    // Generate and download the Excel file
    XLSX.writeFile(wb, 'DeviceLogs.xlsx');
});

function confirmDeletion() {
        if (confirm("Are you sure you want to clear the logs? This action cannot be undone.")) {
            document.getElementById('dltBtn').submit();
        } else {
            // Optional: Provide feedback or perform other actions if user cancels
            alert("Operation canceled.");
        }
    }
    
        setTimeout(function() {
        location.reload();
        }, 5000);

}  );