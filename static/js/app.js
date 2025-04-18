// static/js/app.js

document.addEventListener('DOMContentLoaded', () => {
    // --- Global Variables ---
    let allPlaylists = []; // Stores the complete list fetched from backend
    let filteredPlaylists = []; // Stores the currently filtered list (based on search)
    let currentDisplayPage = 1; // Current page number being displayed (frontend pagination)
    const PLAYLIST_DISPLAY_LIMIT = 25; // How many items to show per page in the frontend
    let searchTimeout = null; // For debouncing search input
    let currentDevices = []; // Store fetched devices globally for the form

    // --- DOM Elements ---
    const loginButton = document.getElementById('login-button');
    const logoutButton = document.getElementById('logout-button');
    const mainAppDiv = document.getElementById('main-app');
    const playlistListUl = document.getElementById('playlist-list');
    const scheduleListUl = document.getElementById('schedule-list');
    const refreshPlaylistsBtn = document.getElementById('refresh-playlists');
    const refreshSchedulesBtn = document.getElementById('refresh-schedules');
    const scheduleFormContainer = document.getElementById('schedule-form-container');
    const scheduleForm = document.getElementById('schedule-form');
    const formTitle = document.getElementById('form-title');
    const formPlaylistName = document.getElementById('form-playlist-name');
    const formPlaylistUri = document.getElementById('form-playlist-uri');
    const formInputPlaylistUri = document.getElementById('form-input-playlist-uri');
    const formInputPlaylistName = document.getElementById('form-input-playlist-name');
    const formDeviceSelect = document.getElementById('form-device');
    const formStartTime = document.getElementById('form-start-time');
    const formStopTime = document.getElementById('form-stop-time');
    const formVolume = document.getElementById('form-volume');
    const formTimezone = document.getElementById('form-timezone');
    const formScheduleId = document.getElementById('schedule-id');
    const cancelScheduleButton = document.getElementById('cancel-schedule-button');
    const playNowFormButton = document.getElementById('play-now-form-button');
    const selectAllDaysBtn = document.getElementById('select-all-days');
    const selectNoDaysBtn = document.getElementById('select-no-days');
    const tabButtons = document.querySelectorAll('.tab-button');
    const tabContents = document.querySelectorAll('.tab-content');
    const playlistSearchInput = document.getElementById('playlist-search');
    const playlistPaginationDiv = document.getElementById('playlist-pagination');
    const playlistPrevBtn = document.getElementById('playlist-prev');
    const playlistNextBtn = document.getElementById('playlist-next');
    const playlistPageInfo = document.getElementById('playlist-page-info');

    // --- Initialization ---
    function init() {
        console.log("App initializing...");
        // Check login status - handled by Flask template initially
        if (mainAppDiv) { // Only add listeners if logged in
            setupEventListeners();
            loadPlaylists(); // Load initial full list
            loadSchedules();
            loadDevices(); // Load devices for the form dropdown
        } else if (loginButton) {
            // Add listener only if login button exists
            loginButton.addEventListener('click', () => {
                window.location.href = '/login'; // Redirect to Flask login route
            });
        }
    }

    // --- Event Listeners Setup ---
    function setupEventListeners() {
        if (logoutButton) logoutButton.addEventListener('click', () => window.location.href = '/logout');
        if (refreshPlaylistsBtn) refreshPlaylistsBtn.addEventListener('click', loadPlaylists); // Refresh reloads all
        if (refreshSchedulesBtn) refreshSchedulesBtn.addEventListener('click', loadSchedules);
        if (playlistSearchInput) playlistSearchInput.addEventListener('input', handlePlaylistFilterInput); // Use specific handler
        if (scheduleForm) scheduleForm.addEventListener('submit', handleSaveSchedule);
        if (cancelScheduleButton) cancelScheduleButton.addEventListener('click', hideScheduleForm);
        if (playNowFormButton) playNowFormButton.addEventListener('click', handlePlayNowFromForm);
        if (selectAllDaysBtn) selectAllDaysBtn.addEventListener('click', () => toggleAllDays(true));
        if (selectNoDaysBtn) selectNoDaysBtn.addEventListener('click', () => toggleAllDays(false));

        // Tab switching
        tabButtons.forEach(button => {
            button.addEventListener('click', () => {
                const targetTabId = button.getAttribute('data-tab');
                tabButtons.forEach(btn => btn.classList.remove('active'));
                tabContents.forEach(content => content.classList.remove('active'));
                button.classList.add('active');
                document.getElementById(targetTabId).classList.add('active');
            });
        });

        // Event delegation for dynamically added buttons in lists
        if (playlistListUl) playlistListUl.addEventListener('click', handlePlaylistClick);
        if (scheduleListUl) scheduleListUl.addEventListener('click', handleScheduleActionClick);

        // Pagination buttons
        if (playlistPrevBtn) playlistPrevBtn.addEventListener('click', () => changeDisplayPage(-1));
        if (playlistNextBtn) playlistNextBtn.addEventListener('click', () => changeDisplayPage(1));
    }

    // --- API Call Functions ---
    async function fetchData(url, options = {}) {
        // Default headers if none provided
        if (!options.headers) {
             options.headers = {};
        }
        // Add content type for POST/PUT if body is JSON (common case)
        if (options.body && typeof options.body === 'string' && !options.headers['Content-Type']) {
             options.headers['Content-Type'] = 'application/json';
        }

        try {
            const response = await fetch(url, options);
            // Check for 401 Unauthorized first
            if (response.status === 401) {
                console.error("API Error 401: Unauthorized. Session likely expired.");
                alert("Your session may have expired. Please log in again.");
                window.location.href = '/logout'; // Force re-login
                return null; // Stop processing
            }
            // Check for other errors
            if (!response.ok) {
                let errorData = { error: `HTTP error ${response.status}` };
                try { errorData = await response.json(); } catch (e) { errorData.error = errorData.error + `: ${response.statusText}`; }
                console.error(`API Error (${url}): ${response.status}`, errorData);
                alert(`Error: ${errorData.error || `Failed to fetch data from ${url}`}`);
                return null; // Indicate failure
            }
            if (response.status === 204) { return { success: true }; } // Handle No Content
            return await response.json(); // Parse JSON
        } catch (error) {
            console.error(`Network/Fetch Error (${url}):`, error);
            alert(`A network error occurred. Please check your connection or try again later. See console for details.`);
            return null; // Indicate failure
        }
    }


    // --- Data Loading Functions ---
    async function loadPlaylists() {
        console.log("Loading ALL playlists from backend...");
        playlistListUl.innerHTML = '<li>Loading playlists...</li>';
        playlistPaginationDiv.style.display = 'none';
        playlistSearchInput.value = ''; // Clear search on full reload

        const url = `/api/playlists`; // Fetches the full list now
        const data = await fetchData(url);

        if (data) {
            allPlaylists = data; // Store the full list
            console.log(`Loaded ${allPlaylists.length} playlists total.`);
            filterAndDisplayPlaylists(); // Call master function to filter (with empty term) and display page 1
        } else {
            allPlaylists = [];
            filteredPlaylists = [];
            playlistListUl.innerHTML = '<li>Failed to load playlists.</li>';
            renderPaginationControls(); // Update controls (will show none)
        }
    }

    async function loadDevices() {
        console.log("Loading devices...");
        const devices = await fetchData('/api/devices');
        currentDevices = devices || []; // Store globally
        // Render into the form select now, so it's ready when form opens
        renderDeviceOptions(currentDevices);
    }

     async function loadSchedules() {
        console.log("Loading schedules...");
        scheduleListUl.innerHTML = '<li>Loading schedules...</li>';
        const schedules = await fetchData('/api/schedules');
        renderSchedules(schedules || []);
    }

    // --- Filtering and Display Logic ---

    function filterAndDisplayPlaylists() {
        const searchTerm = playlistSearchInput.value.toLowerCase().trim();

        // Filter the master list
        if (searchTerm) {
            filteredPlaylists = allPlaylists.filter(playlist =>
                playlist.name.toLowerCase().includes(searchTerm)
            );
        } else {
            // If no search term, the filtered list is the full list
            filteredPlaylists = [...allPlaylists]; // Use spread to copy
        }

        // Reset to page 1 whenever the filter changes
        // Note: This is handled in the input handler which calls this function

        // Display the first page of the filtered results
        renderPaginatedView();
    }

    function renderPaginatedView() {
        // Calculate the slice of the *filtered* list to display
        const startIndex = (currentDisplayPage - 1) * PLAYLIST_DISPLAY_LIMIT;
        const endIndex = startIndex + PLAYLIST_DISPLAY_LIMIT;
        const playlistsToShow = filteredPlaylists.slice(startIndex, endIndex);

        // Render just the slice
        renderPlaylistSlice(playlistsToShow);
        // Update pagination controls based on the *filtered* list length
        renderPaginationControls();
    }

    function renderPlaylistSlice(playlistsSlice) {
        playlistListUl.innerHTML = ''; // Clear previous page's items
        if (!playlistsSlice || playlistsSlice.length === 0) {
            const message = playlistSearchInput.value.trim() ?
                 `<li>No playlists found matching "${playlistSearchInput.value}".</li>` :
                 '<li>No playlists found.</li>';
            playlistListUl.innerHTML = message;
            return;
        }
        playlistsSlice.forEach(p => {
            const li = document.createElement('li');
            // Basic escaping for display
            const safeName = p.name.replace(/</g, "&lt;").replace(/>/g, "&gt;");
            const safeUri = p.uri.replace(/</g, "&lt;").replace(/>/g, "&gt;");
            // Store original name in data-name for the form
            li.innerHTML = `${safeName} <button class="add-schedule-btn" data-uri="${safeUri}" data-name="${p.name}">Schedule</button>`;
            playlistListUl.appendChild(li);
        });
    }

    function renderPaginationControls() {
        if (!playlistPaginationDiv) return;

        const totalFilteredItems = filteredPlaylists.length;
        const totalPages = Math.ceil(totalFilteredItems / PLAYLIST_DISPLAY_LIMIT);

        if (totalPages <= 1) {
            playlistPaginationDiv.style.display = 'none'; // Hide if only one page or empty
            return;
        }

        playlistPaginationDiv.style.display = 'flex';
        playlistPageInfo.textContent = `Page ${currentDisplayPage} of ${totalPages} (${totalFilteredItems} items)`;
        playlistPrevBtn.disabled = (currentDisplayPage <= 1);
        playlistNextBtn.disabled = (currentDisplayPage >= totalPages);

        // Store total pages for boundary checks in changeDisplayPage (optional but good)
        playlistPaginationDiv.dataset.totalPages = totalPages;
    }

    function renderDeviceOptions(devices) {
        // Keep track of current selection only if form is open? Or just always render?
        // Let's always render, assuming form might open later.
        // const currentSelection = formDeviceSelect.value; // Preserve selection if possible? Might be complex if list changes.
        formDeviceSelect.innerHTML = '<option value="">-- Select Device --</option>';
        if (!devices || devices.length === 0) {
            formDeviceSelect.innerHTML += '<option value="" disabled>No active devices found</option>';
            return;
        }
        devices.forEach(d => {
            const option = document.createElement('option');
            option.value = d.id;
            // Basic escaping for device name
            option.textContent = `${d.name.replace(/</g, "&lt;").replace(/>/g, "&gt;")} (${d.type})`;
            if (d.is_active) {
                 option.textContent += " ★ Active";
                 option.style.fontWeight = 'bold';
            }
            formDeviceSelect.appendChild(option);
        });
        // Restore selection might be better done when opening the form for editing
    }

    function renderSchedules(schedules) {
        scheduleListUl.innerHTML = ''; // Clear previous
       if (!schedules || schedules.length === 0) {
           scheduleListUl.innerHTML = '<li>No schedules created yet.</li>';
           return;
       }

       // Note: Schedules are now pre-sorted by the backend
       schedules.forEach(s => {
        
           const li = document.createElement('li');
           const daysStr = s.days_of_week ? getDaysString(s.days_of_week) : (s.play_once_triggered ? "Played Once" : "Play Once");
           const stopStr = s.stop_time_local ? ` - ${s.stop_time_local}` : "";
           const volumeStr = s.volume !== null ? ` | Vol: ${s.volume}%` : "";
           const statusStr = s.is_active ? "Active" : "Paused";
           const toggleBtnText = s.is_active ? "Pause" : "Unpause";
           // Use specific CSS classes for status (see CSS changes below)
           const statusClassName = s.is_active ? "status-active" : "status-paused";
           const safePlaylistName = (s.playlist_name || 'Unknown Playlist').replace(/</g, "&lt;").replace(/>/g, "&gt;");
           const safeDeviceName = (s.target_device_name || s.target_device_id || 'Unknown Device').replace(/</g, "&lt;").replace(/>/g, "&gt;");

           // --- Calculate and Format Next Run Time ---
        let nextRunStr = "N/A"; // Default
        const nextTimeUTC_ISO = s._next_play_time_utc_iso; // Get the value from backend data

        // *** ADD LOGGING HERE ***
        console.log(`Schedule ID ${s.id}: Raw _next_play_time_utc from backend: ${nextTimeUTC_ISO}`);

        if (nextTimeUTC_ISO) {
            try {
                const nextDate = new Date(nextTimeUTC_ISO);

                // *** ADD LOGGING HERE ***
                console.log(`Schedule ID ${s.id}: Parsed JS Date object: ${nextDate.toString()}`);
                console.log(`Schedule ID ${s.id}: JS Date ISOString: ${nextDate.toISOString()}`); // Log the UTC value JS holds

                const options = { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: 'numeric' };
                nextRunStr = nextDate.toLocaleString(undefined, options);

                // *** ADD LOGGING HERE ***
                console.log(`Schedule ID ${s.id}: Formatted by toLocaleString: ${nextRunStr}`);

            } catch (e) {
                console.error("Error parsing next run date:", nextTimeUTC_ISO, e);
                nextRunStr = "Error parsing date";
            }
        } else if (!s.is_active) {
            nextRunStr = "Paused";
        } else if (s.play_once_triggered) {
             nextRunStr = "Already Played";
        }
           // --- End Next Run Time Calculation ---


           // Use spans for better control over inline elements and labels
           const shuffleStr = s.shuffle_state ? "Yes" : "No";
           li.innerHTML = `
                <div class="schedule-header">
                    <strong>${safePlaylistName}</strong>
                    <span class="schedule-device">on ${safeDeviceName}</span>
                </div>
                <div class="schedule-details">
                    <span>Time: ${s.start_time_local}${stopStr} (${s.timezone || '?'})</span>
                    <span>Days: ${daysStr}</span>
                    ${volumeStr ? `<span>Vol: ${s.volume}%</span>` : ''}
                    <span>Shuffle: ${shuffleStr}</span>
                </div>
                <div class="schedule-status-line">
                    <span class="schedule-info-label">Next Run:</span> <span class="schedule-next-run">${nextRunStr}</span>
                </div>
                 <div class="schedule-status-line">
                    <span class="schedule-info-label">Status:</span> <span class="schedule-status ${statusClassName}">${statusStr}</span>
                 </div>
                <div class="schedule-actions">
                    <button class="play-now-btn" data-id="${s.id}" title="Play this schedule's playlist/device now">▶ Play Now</button>
                    <button class="toggle-active-btn" data-id="${s.id}" title="${toggleBtnText} this schedule">${toggleBtnText}</button>
                    <button class="edit-schedule-btn" data-id="${s.id}" title="Edit this schedule">✏️ Edit</button>
                    <button class="duplicate-schedule-btn" data-id="${s.id}" title="Duplicate this schedule">📄 Duplicate</button>
                    <button class="delete-schedule-btn" data-id="${s.id}" title="Delete this schedule">🗑️ Delete</button>
                </div>
           `;
           // Store full data for editing
           li.dataset.scheduleData = JSON.stringify(s);
           scheduleListUl.appendChild(li);
       });
   }

    // --- Event Handlers ---
     function changeDisplayPage(direction) {
         const totalFilteredItems = filteredPlaylists.length;
         const totalPages = Math.ceil(totalFilteredItems / PLAYLIST_DISPLAY_LIMIT);
         const nextPage = currentDisplayPage + direction;

         if (nextPage >= 1 && nextPage <= totalPages) {
             currentDisplayPage = nextPage;
             renderPaginatedView(); // Re-render with the new page slice
         } else {
             console.log("Boundary hit, page not changed.");
         }
    }

    function handlePlaylistFilterInput() {
         // Debounce the filtering
         clearTimeout(searchTimeout);
         searchTimeout = setTimeout(() => {
             currentDisplayPage = 1; // Reset to page 1 on new filter
             filterAndDisplayPlaylists(); // Filter and display page 1 of results
         }, 300); // 300ms delay
    }

    function handlePlaylistClick(event) {
        // Handles clicks within the playlist list (delegated)
        if (event.target.classList.contains('add-schedule-btn')) {
            const button = event.target;
            // Retrieve original name from data attribute
            const uri = button.getAttribute('data-uri');
            const name = button.getAttribute('data-name'); // Use original name here
            openScheduleForm({ playlist_uri: uri, playlist_name: name }); // Open form for adding
        }
    }

     async function handleScheduleActionClick(event) {
         // Handles clicks within the schedule list (delegated)
         const button = event.target.closest('button');
         if (!button) return;

         const scheduleId = button.getAttribute('data-id');
         if (!scheduleId) return;

         if (button.classList.contains('play-now-btn')) {
             console.log(`Playing schedule ${scheduleId} now...`);
             button.textContent = "Playing..."; button.disabled = true;
             const result = await fetchData(`/api/schedules/${scheduleId}/play_now`, { method: 'POST' });
             if (result) { setTimeout(() => { alert(result.message || "Playback initiated."); button.textContent = "▶ Play Now"; button.disabled = false; }, 500); }
             else { button.textContent = "▶ Play Now"; button.disabled = false; }
         } else if (button.classList.contains('toggle-active-btn')) {
              console.log(`Toggling schedule ${scheduleId}...`);
             const result = await fetchData(`/api/schedules/${scheduleId}/toggle`, { method: 'PUT' });
             if (result) loadSchedules();
         } else if (button.classList.contains('edit-schedule-btn')) {
              console.log(`Editing schedule ${scheduleId}...`);
             const scheduleData = JSON.parse(button.closest('li').dataset.scheduleData || '{}');
             openScheduleForm(scheduleData);
            } else if (button.classList.contains('duplicate-schedule-btn')) {
                // --- ADD THIS BLOCK ---
                console.log(`Duplicating schedule ${scheduleId}...`);
                const listItem = button.closest('li');
                if (listItem && listItem.dataset.scheduleData) {
                    try {
                        const scheduleData = JSON.parse(listItem.dataset.scheduleData);
    
                        // Prepare data for a NEW schedule based on the old one
                        const duplicatedData = { ...scheduleData }; // Create a copy
    
                        // Remove fields specific to the original instance
                        delete duplicatedData.id;
                        delete duplicatedData.last_triggered_utc;
                        delete duplicatedData.play_once_triggered;
                        // Remove calculated fields added by backend/frontend
                        delete duplicatedData._next_play_time_utc_iso;
                        delete duplicatedData._sort_obj; // If this key exists
    
                        // Open the form, pre-filled with the copied data (without ID)
                        // openScheduleForm handles 'Add Schedule' title when no ID is present
                        openScheduleForm(duplicatedData);
    
                    } catch (e) {
                        console.error("Error parsing schedule data for duplication:", e);
                        alert("Error: Could not read schedule data for duplication.");
                    }
                } else {
                     console.error(`Could not find schedule data for ID ${scheduleId} to duplicate.`);
                     alert("Error: Could not find schedule data to duplicate.");
                }
                // --- END ADDED BLOCK ---
    
         } else if (button.classList.contains('delete-schedule-btn')) {
             if (confirm('Are you sure you want to delete this schedule?')) {
                 console.log(`Deleting schedule ${scheduleId}...`);
                  const result = await fetchData(`/api/schedules/${scheduleId}`, { method: 'DELETE' });
                 if (result) { console.log("Delete successful", result); loadSchedules(); }
                 else { console.log("Delete failed"); }
             }
         }
    }

    async function handleSaveSchedule(event) {
        // Handles submission of the add/edit schedule form
        event.preventDefault();
        console.log("Saving schedule...");

        const scheduleId = formScheduleId.value;
        const isEditing = !!scheduleId;

        const selectedDays = Array.from(document.querySelectorAll('#schedule-form input[id^="day-"]:checked')).map(cb => cb.value);
        const daysOfWeekStr = selectedDays.join(',');
        const targetDeviceId = formDeviceSelect.value;
        const targetDeviceName = formDeviceSelect.options[formDeviceSelect.selectedIndex]?.text.split(' (')[0];
        const startTime = formStartTime.value;
        const timezone = formTimezone.value || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

        if (!targetDeviceId) { alert("Please select a target device."); return; }
        if (!startTime) { alert("Please select a start time."); return; }
        if (!timezone) { alert("Please specify a timezone."); return; }
        if (!daysOfWeekStr && !isEditing) {
             if (!confirm("No days selected. Schedule will play once when conditions match next, then stop. Continue?")) { return; }
        }
        const shuffleState = document.getElementById('form-shuffle').checked;

        const scheduleData = {
            playlist_uri: formInputPlaylistUri.value,
            playlist_name: formInputPlaylistName.value,
            target_device_id: targetDeviceId,
            target_device_name: targetDeviceName,
            days_of_week: daysOfWeekStr,
            start_time_local: startTime,
            stop_time_local: formStopTime.value || null,
            volume: formVolume.value ? parseInt(formVolume.value, 10) : null,
            timezone: timezone,
            shuffle_state: shuffleState,
        };
        // Preserve is_active status when editing if form doesn't have an explicit toggle
         if (isEditing) {
             const originalData = JSON.parse(document.querySelector(`li[data-schedule-data*='"id":${scheduleId}']`)?.dataset.scheduleData || '{}');
             scheduleData.is_active = originalData?.is_active ?? 1; // Keep original status
              // Reset play_once_triggered only if days change from 'play once' to specific days or vice-versa
             if((daysOfWeekStr && !originalData?.days_of_week) || (!daysOfWeekStr && originalData?.days_of_week)) {
                  scheduleData.play_once_triggered = 0; // Backend should handle this based on days_of_week really
             }
         }

        console.log("Data to save:", scheduleData);
        const url = isEditing ? `/api/schedules/${scheduleId}` : '/api/schedules';
        const method = isEditing ? 'PUT' : 'POST';

        const result = await fetchData(url, { method: method, body: JSON.stringify(scheduleData) });
        if (result && !result.error) {
            console.log("Save successful:", result);
            hideScheduleForm(); loadSchedules();
        } else { console.error("Failed to save schedule."); }
    }

     function handlePlayNowFromForm() {
         // Handles the "Play Now" button within the schedule form
         const playlistUri = formInputPlaylistUri.value;
         const deviceId = formDeviceSelect.value;
         const volume = formVolume.value ? parseInt(formVolume.value, 10) : null;

         if (!playlistUri || !deviceId) { alert("Please select playlist and device."); return; }

         console.log(`Playing playlist ${playlistUri} on device ${deviceId} now...`);
         playNowFormButton.textContent = "Playing..."; playNowFormButton.disabled = true;

         fetchData('/api/play_now', { method: 'POST', body: JSON.stringify({ playlist_uri: playlistUri, device_id: deviceId, volume: volume }) })
         .then(result => {
              if (result) { setTimeout(() => { alert(result.message || "Playback initiated."); playNowFormButton.textContent = "Play Now"; playNowFormButton.disabled = false; }, 500); }
              else { playNowFormButton.textContent = "Play Now"; playNowFormButton.disabled = false; }
         });
    }


    // --- UI Helper Functions ---
    function openScheduleForm(data = {}) {
        // 1. Reset the form to clear previous values
        scheduleForm.reset();
        formScheduleId.value = ''; // Clear hidden ID field
    
        // 2. Always try to populate fields from the passed 'data' object
        formPlaylistName.textContent = data.playlist_name || 'N/A';
        formPlaylistUri.textContent = data.playlist_uri || 'N/A';
        formInputPlaylistUri.value = data.playlist_uri || '';
        formInputPlaylistName.value = data.playlist_name || '';
    
        // Re-render device options to ensure they are fresh *before* setting value
        renderDeviceOptions(currentDevices); // Assumes currentDevices is populated
        // Set device if available in data
        if (data.target_device_id) {
            formDeviceSelect.value = data.target_device_id;
            // Small delay might sometimes help ensure options are rendered before setting value
            // setTimeout(() => { formDeviceSelect.value = data.target_device_id; }, 50);
        } else {
             formDeviceSelect.value = ''; // Explicitly clear if not in data
        }
    
    
        // Reset days checkboxes first
        toggleAllDays(false);
        // Set days if available in data
        const days = data.days_of_week ? data.days_of_week.split(',').map(d => d.trim()) : [];
        days.forEach(dayIndex => {
            try {
                const dayName = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'][parseInt(dayIndex, 10)];
                if (dayName) {
                    const checkbox = document.getElementById(`day-${dayName}`);
                    if (checkbox) {
                        checkbox.checked = true;
                    } else {
                        console.warn(`Checkbox for day index ${dayIndex} (day-${dayName}) not found.`);
                    }
                }
            } catch (e) { console.error("Error parsing day index:", dayIndex, e); }
        });
    
        // Set time, volume, timezone if available in data
        formStartTime.value = data.start_time_local || '';
        formStopTime.value = data.stop_time_local || '';
        formVolume.value = data.volume !== null ? data.volume : '';
        // Use provided timezone, otherwise default to browser/sensible default
        formTimezone.value = data.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'Europe/Paris';
    
        // Set shuffle state if available in data
        const shuffleCheckbox = document.getElementById('form-shuffle');
        if (shuffleCheckbox) { // Ensure checkbox exists
            shuffleCheckbox.checked = data.shuffle_state ? true : false; // Set checked based on data
        }
    
        // 3. Set Form Title and ID *only if editing*
        if (data.id) {
            formTitle.textContent = 'Edit Schedule';
            formScheduleId.value = data.id; // Set the hidden ID field
        } else if (Object.keys(data).length > 0 && data.playlist_uri) {
            // If data was passed but it has no ID, assume it's a duplicate
            formTitle.textContent = 'Add Schedule (from Duplicate)';
            // Ensure default timezone is set only for brand new, not duplicate
        } else {
            // No data passed or empty object, so it's a new schedule from scratch
            formTitle.textContent = 'Add Schedule';
            // Set default timezone for brand new schedules
            formTimezone.value = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Europe/Paris';
        }
    
        // 4. Show and scroll to the form
        scheduleFormContainer.style.display = 'block';
        scheduleFormContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function hideScheduleForm() {
        // Hides and resets the schedule form
        scheduleFormContainer.style.display = 'none';
        scheduleForm.reset();
        formScheduleId.value = '';
    }

     function toggleAllDays(select) {
        // Checks or unchecks all day-of-week checkboxes
        const checkboxes = document.querySelectorAll('#schedule-form input[id^="day-"]');
        checkboxes.forEach(cb => cb.checked = select);
    }

    function getDaysString(daysOfWeekStr) {
        // Helper to convert "0,1,6" to "Mon, Tue, Sun"
        if (!daysOfWeekStr) return "Once"; // Should match backend logic for empty string meaning play once
        const daysMap = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
        try {
            return daysOfWeekStr.split(',')
                               .map(d => parseInt(d.trim(), 10))
                               .filter(i => i >= 0 && i < 7)
                               .sort((a, b) => a - b)
                               .map(i => daysMap[i])
                               .join(', ');
        } catch (e) { return "Invalid Days"; }
    }


    // --- Start the App ---
    init();

}); // End DOMContentLoaded