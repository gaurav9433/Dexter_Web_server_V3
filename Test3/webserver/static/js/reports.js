document.addEventListener('DOMContentLoaded', function() {
    const downloadBtn = document.getElementById('downloadBtn');
    
    downloadBtn.addEventListener('click', function() {
        const reportType = document.getElementById('reportType').value;
        let fileName;
        let fileContent;
        
        // Get current date for the report filename
        const now = new Date();
        const dateStr = now.toISOString().split('T')[0]; // YYYY-MM-DD format
        
        switch (reportType) {
            case 'daily':
                fileName = `daily_report_${dateStr}.txt`;
                fileContent = generateDailyReport();
                break;
            case 'monthly':
                fileName = `monthly_report_${dateStr}.txt`;
                fileContent = generateMonthlyReport();
                break;
            case 'quarterly':
                fileName = `quarterly_report_${dateStr}.txt`;
                fileContent = generateQuarterlyReport();
                break;
            case 'annual':
                fileName = `annual_report_${dateStr}.txt`;
                fileContent = generateAnnualReport();
                break;
            default:
                fileName = `report_${dateStr}.txt`;
                fileContent = 'This is the default report content.';
        }
        
        // Create an anchor element
        const a = document.createElement('a');
        
        // Set the file name
        a.download = fileName;
        
        // Create a blob object
        const blob = new Blob([fileContent], { type: 'text/plain' });
        
        // Create an object URL
        a.href = URL.createObjectURL(blob);
        
        // Append the anchor to the body
        document.body.appendChild(a);
        
        // Trigger the download
        a.click();
        
        // Remove the anchor from the document
        document.body.removeChild(a);
        
        // Clean up the object URL to free memory
        URL.revokeObjectURL(a.href);
    });
    
    // Sample report generation functions - replace with actual data in production
    function generateDailyReport() {
        return `DAILY REPORT - ${new Date().toLocaleDateString()}
---------------------------------
Device Status Summary:
- Active Devices: 42
- Inactive Devices: 3
- Devices with Warnings: 5

Event Log Summary:
- Critical Events: 0
- Warning Events: 12
- Information Events: 156

Performance Metrics:
- Average Response Time: 120ms
- Peak Usage Time: 14:30
- Resource Utilization: 62%
`;
    }
    
    function generateMonthlyReport() {
        return `MONTHLY REPORT - ${new Date().toLocaleDateString()}
-----------------------------------
Monthly Device Status:
- Active Devices: 45
- Inactive Devices: 2
- Average Uptime: 99.7%

Event Trends:
- Critical Events: 3
- Warning Events: 47
- Information Events: 625

System Performance:
- Average Load: 58%
- Peak Usage Day: Tuesday
- Maintenance Events: 2
`;
    }
    
    function generateQuarterlyReport() {
        return `QUARTERLY REPORT - ${new Date().toLocaleDateString()}
--------------------------------------
Quarterly Overview:
- Total Devices: 47
- New Devices: 5
- Decommissioned Devices: 2

Performance Analysis:
- System Uptime: 99.5%
- Average Response Time Trend: Improving (125ms → 118ms)
- Resource Utilization: 65% average

Incident Summary:
- Critical Incidents: 6
- Average Resolution Time: 45 minutes
- Most Common Issue: Network Connectivity (38%)
`;
    }
    
    function generateAnnualReport() {
        return `ANNUAL REPORT - ${new Date().toLocaleDateString()}
----------------------------------
Annual System Performance:
- Overall Uptime: 99.3%
- Total Devices Managed: 52
- Device Turnover Rate: 12%

Critical Statistics:
- Total Events Processed: 28,546
- Critical Incidents: 24
- Average Monthly Active Devices: 44

Performance Trends:
- Q1: 97.8% uptime
- Q2: 99.1% uptime
- Q3: 99.5% uptime
- Q4: 99.8% uptime

Recommendations:
- Schedule maintenance for devices #103, #156
- Consider upgrading network infrastructure
- Implement automated alerting for critical events
`;
    }
});
