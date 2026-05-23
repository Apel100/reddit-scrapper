// CineNuggets Frontend Application Logic

// Detect API base URL dynamically
const API_BASE = (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") 
    ? "" 
    : "http://localhost:5000";

// Global Application State
let appSettings = {
    comment_threshold: 15,
    lookback_val: 16,
    lookback_unit: "Hours",
    max_workers: 15,
    save_folder: "",
    subreddits: [],
    keywords: ""
};

let pollTimer = null;
let lastLogIndex = 0;
let isScraperActive = false;
let currentFileRawContent = "";
let activeResultFile = "";

// Initialize App
document.addEventListener("DOMContentLoaded", () => {
    // Sliders dynamic display updating
    setupSliders();
    
    // Load config and results lists
    loadSettings();
    loadResultsList();
    
    // Check initial running status
    checkStatus();
    
    // Start general status checker timer (polls server connection status)
    setInterval(checkStatus, 3000);
});

// Setup Slider Handlers
function setupSliders() {
    const sliders = [
        { id: "comment-threshold", display: "comment-threshold-val" },
        { id: "lookback-val", display: "lookback-val-display" },
        { id: "max-workers", display: "max-workers-val" }
    ];
    
    sliders.forEach(slider => {
        const el = document.getElementById(slider.id);
        const display = document.getElementById(slider.display);
        if (el && display) {
            el.addEventListener("input", (e) => {
                display.textContent = e.target.value;
            });
        }
    });
}

// Show Alert Toast Message
function showToast(message, type = "success") {
    const toast = document.getElementById("toast");
    toast.textContent = message;
    toast.className = `toast ${type === "error" ? "danger-bg" : ""}`;
    toast.classList.remove("d-none");
    
    setTimeout(() => {
        toast.classList.add("d-none");
    }, 3500);
}

// Switch Sidebar Config Tabs (Subreddits vs Keywords)
function switchConfigTab(tabName) {
    document.querySelectorAll(".config-tab-btn").forEach(btn => {
        btn.classList.remove("active");
    });
    document.querySelectorAll(".config-tab-content").forEach(content => {
        content.classList.remove("active");
    });
    
    if (tabName === "subreddits") {
        document.querySelector(".config-tab-btn:nth-child(1)").classList.add("active");
        document.getElementById("config-subreddits").classList.add("active");
    } else {
        document.querySelector(".config-tab-btn:nth-child(2)").classList.add("active");
        document.getElementById("config-keywords").classList.add("active");
    }
}

// Switch Main Dashboard Viewport Tabs (Console vs Results)
function switchMainTab(tabName) {
    document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.classList.remove("active");
    });
    document.querySelectorAll(".tab-content").forEach(content => {
        content.classList.remove("active");
    });
    
    if (tabName === "console") {
        document.getElementById("tab-btn-console").classList.add("active");
        document.getElementById("tab-content-console").classList.add("active");
    } else {
        document.getElementById("tab-btn-results").classList.add("active");
        document.getElementById("tab-content-results").classList.add("active");
        loadResultsList(); // Automatically refresh results list when opening tab
    }
}

// --- API ACTIONS ---

// Fetch configurations from backend
async function loadSettings() {
    try {
        const response = await fetch(`${API_BASE}/api/settings?_t=${Date.now()}`);
        if (!response.ok) throw new Error("Failed to load settings");
        
        appSettings = await response.json();
        
        // Populate inputs
        document.getElementById("comment-threshold").value = appSettings.comment_threshold;
        document.getElementById("comment-threshold-val").textContent = appSettings.comment_threshold;
        
        document.getElementById("lookback-val").value = appSettings.lookback_val;
        document.getElementById("lookback-val-display").textContent = appSettings.lookback_val;
        document.getElementById("lookback-unit").value = appSettings.lookback_unit;
        
        document.getElementById("max-workers").value = appSettings.max_workers;
        document.getElementById("max-workers-val").textContent = appSettings.max_workers;
        
        document.getElementById("save-folder").value = appSettings.save_folder || "Default script directory";
        document.getElementById("keywords-input").value = appSettings.keywords;
        
        renderSubredditChips();
        updateConnectionBadge(true);
    } catch (error) {
        console.error(error);
        updateConnectionBadge(false);
    }
}

// Save config form to backend
async function saveSettings() {
    appSettings.comment_threshold = parseInt(document.getElementById("comment-threshold").value);
    appSettings.lookback_val = parseInt(document.getElementById("lookback-val").value);
    appSettings.lookback_unit = document.getElementById("lookback-unit").value;
    appSettings.max_workers = parseInt(document.getElementById("max-workers").value);
    appSettings.keywords = document.getElementById("keywords-input").value;
    
    try {
        const response = await fetch(`${API_BASE}/api/settings`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(appSettings)
        });
        
        if (!response.ok) throw new Error("Failed to save settings");
        const res = await response.json();
        showToast(res.message || "Settings saved successfully!");
    } catch (error) {
        showToast("Error: Could not save settings.", "error");
    }
}

// Subreddit Chips Operations
function renderSubredditChips() {
    const list = document.getElementById("subreddits-list");
    list.innerHTML = "";
    
    if (appSettings.subreddits.length === 0) {
        list.innerHTML = `<span class="help-text" style="padding: 10px;">No subreddits added.</span>`;
        return;
    }
    
    appSettings.subreddits.forEach((sub, index) => {
        const chip = document.createElement("div");
        chip.className = "chip";
        chip.innerHTML = `
            r/${sub}
            <span class="delete-btn" onclick="deleteSubreddit(${index})">&times;</span>
        `;
        list.appendChild(chip);
    });
}

function addSubreddit() {
    const input = document.getElementById("new-subreddit");
    let name = input.value.trim().replace(/^r\//i, ""); // strip "r/" if typed
    
    if (!name) return;
    
    if (appSettings.subreddits.includes(name)) {
        showToast(`r/${name} is already in the list!`, "error");
        input.value = "";
        return;
    }
    
    appSettings.subreddits.push(name);
    renderSubredditChips();
    input.value = "";
    saveSettings(); // Auto save
}

function deleteSubreddit(index) {
    appSettings.subreddits.splice(index, 1);
    renderSubredditChips();
    saveSettings(); // Auto save
}

function updateKeywords() {
    const input = document.getElementById("keywords-input");
    appSettings.keywords = input.value.trim();
    saveSettings();
}

// Start Sc scraper execution
async function startScraper() {
    // Auto save settings first
    await saveSettings();
    
    try {
        const response = await fetch(`${API_BASE}/api/start`, { method: "POST" });
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.message || "Scraper start failed.");
        }
        
        // Reset local logs index
        lastLogIndex = 0;
        document.getElementById("console-viewport").innerHTML = '<div class="log-line system-log">[SYSTEM] Starting scraping session...</div>';
        
        isScraperActive = true;
        updateScraperStatusBadge(true);
        
        // Toggle buttons visibility
        document.getElementById("btn-start").classList.add("d-none");
        document.getElementById("btn-stop").classList.remove("d-none");
        
        // Switch to console tab
        switchMainTab("console");
        
        // Start polling logs
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(pollLogs, 1000);
        
        showToast("Scraper session initialized.");
    } catch (error) {
        showToast(error.message, "error");
    }
}

// Stop Scraper gracefully
async function stopScraper() {
    try {
        const response = await fetch(`${API_BASE}/api/stop`, { method: "POST" });
        if (!response.ok) throw new Error("Failed to stop scraper.");
        showToast("Stopping process... Cleaning threads.");
    } catch (error) {
        showToast(error.message, "error");
    }
}

// Check status on load or interval
async function checkStatus() {
    try {
        const response = await fetch(`${API_BASE}/api/status?_t=${Date.now()}`);
        if (!response.ok) throw new Error();
        
        const data = await response.json();
        updateConnectionBadge(true);
        
        if (data.is_running) {
            isScraperActive = true;
            updateScraperStatusBadge(true, data.status_message);
            document.getElementById("btn-start").classList.add("d-none");
            document.getElementById("btn-stop").classList.remove("d-none");
            
            // Re-establish polling if not active
            if (!pollTimer) {
                lastLogIndex = 0;
                document.getElementById("console-viewport").innerHTML = '<div class="log-line system-log">[SYSTEM] Connecting to running scrape session...</div>';
                pollTimer = setInterval(pollLogs, 1000);
            }
        } else {
            isScraperActive = false;
            updateScraperStatusBadge(false);
            document.getElementById("btn-start").classList.remove("d-none");
            document.getElementById("btn-stop").classList.add("d-none");
            
            if (pollTimer) {
                clearInterval(pollTimer);
                pollTimer = null;
                loadResultsList(); // Auto refresh on finish
            }
        }
    } catch (error) {
        updateConnectionBadge(false);
    }
}

// Poll Logs during execution
async function pollLogs() {
    try {
        const response = await fetch(`${API_BASE}/api/status?since=${lastLogIndex}&_t=${Date.now()}`);
        if (!response.ok) throw new Error();
        
        const data = await response.json();
        
        // Update stats
        document.getElementById("stat-status").textContent = data.status_message;
        document.getElementById("stat-discovered").textContent = data.stats.discovered;
        document.getElementById("stat-scraped").textContent = data.stats.scraped;
        document.getElementById("stat-errors").textContent = data.stats.errors;
        
        // Progress
        document.getElementById("progress-bar").style.width = `${data.progress_percent}%`;
        document.getElementById("progress-label").textContent = `${data.progress_percent}%`;
        
        // Process new logs
        if (data.logs.length > 0) {
            const viewport = document.getElementById("console-viewport");
            data.logs.forEach(log => {
                const line = document.createElement("div");
                line.className = "log-line";
                line.textContent = log;
                
                // Color codes
                if (log.includes("✅") || log.includes("🎉") || log.includes("complete")) {
                    line.classList.add("success-log");
                } else if (log.includes("❌") || log.includes("failed") || log.includes("[!] Error")) {
                    line.classList.add("error-log");
                } else if (log.includes("[!]") || log.includes("Pausing")) {
                    line.classList.add("warning-log");
                } else if (log.includes(">>>") || log.includes("[SYSTEM]")) {
                    line.classList.add("system-log");
                }
                
                viewport.appendChild(line);
            });
            
            viewport.scrollTop = viewport.scrollHeight;
            lastLogIndex += data.logs.length;
        }
        
        // Handlers for completed status
        if (!data.is_running) {
            clearInterval(pollTimer);
            pollTimer = null;
            isScraperActive = false;
            updateScraperStatusBadge(false);
            
            document.getElementById("btn-start").classList.remove("d-none");
            document.getElementById("btn-stop").classList.add("d-none");
            
            showToast("Scraper finished execution!");
            loadResultsList();
        }
    } catch (e) {
        console.error("Polling error", e);
    }
}

// Update Badges UI
function updateConnectionBadge(connected) {
    const badge = document.getElementById("connection-status");
    if (connected) {
        badge.className = "status-badge connected";
        badge.innerHTML = `<span class="dot"></span> Server Connected`;
    } else {
        badge.className = "status-badge";
        badge.innerHTML = `<span class="dot" style="background-color: #ef4444;"></span> Server Offline`;
    }
}

function updateScraperStatusBadge(active, message = "Running...") {
    const badge = document.getElementById("scraper-status");
    if (active) {
        badge.className = "status-badge active";
        badge.innerHTML = `<span class="dot"></span> ${message}`;
    } else {
        badge.className = "status-badge idle";
        badge.innerHTML = `<span class="dot"></span> Scraper: Idle`;
    }
}

// --- RESULTS BROWSER & COMMENT PARSER ---

// Fetch files list
async function loadResultsList() {
    try {
        const response = await fetch(`${API_BASE}/api/results?_t=${Date.now()}`);
        if (!response.ok) throw new Error("Could not load results.");
        
        const files = await response.json();
        const list = document.getElementById("results-list");
        list.innerHTML = "";
        
        if (files.length === 0) {
            list.innerHTML = `<div class="no-results">No files found. Run the scraper first.</div>`;
            return;
        }
        
        files.forEach(file => {
            const item = document.createElement("div");
            item.className = `result-item ${activeResultFile === file.name ? 'active' : ''}`;
            item.onclick = () => selectResultFile(file.name, item);
            
            // Format name for readable display (remove .txt and clean numbers)
            // e.g. "1_r_popculturechat_Title" -> "Title"
            let readableTitle = file.name.replace(".txt", "");
            const titleParts = readableTitle.split(/_r_[a-zA-Z0-9]+_/i);
            if (titleParts.length >= 2) {
                readableTitle = titleParts[1].replace(/_/g, " ");
            } else {
                readableTitle = readableTitle.replace(/^\d+_r_[a-zA-Z0-9]+_/i, "").replace(/_/g, " ");
            }
            
            item.innerHTML = `
                <span class="result-item-title">${readableTitle}</span>
                <div class="result-item-meta">
                    <span class="badge">r/${file.subreddit}</span>
                    <span>${file.modified}</span>
                </div>
            `;
            list.appendChild(item);
        });
    } catch (e) {
        showToast("Error loading file list.", "error");
    }
}

// Trigger file selection
async function selectResultFile(filename, element) {
    // Update active highlight
    document.querySelectorAll(".result-item").forEach(item => item.classList.remove("active"));
    element.classList.add("active");
    
    activeResultFile = filename;
    
    try {
        const response = await fetch(`${API_BASE}/api/results/content?file=${filename}&_t=${Date.now()}`);
        if (!response.ok) throw new Error();
        
        const data = await response.json();
        currentFileRawContent = data.content;
        
        // Parse metadata and comments
        const parsed = parseScrapedFileContent(data.content);
        
        // Show viewer content state
        document.getElementById("viewer-empty-state").classList.add("d-none");
        const contentState = document.getElementById("viewer-content-state");
        contentState.classList.remove("d-none");
        
        // Render headings
        document.getElementById("viewer-title").textContent = parsed.title;
        document.getElementById("viewer-sub").textContent = parsed.subreddit;
        document.getElementById("viewer-date").textContent = parsed.date;
        
        const redditLink = document.getElementById("viewer-link");
        if (parsed.link) {
            redditLink.href = parsed.link;
            redditLink.style.display = "inline-flex";
        } else {
            redditLink.style.display = "none";
        }
        
        // Parse and render comments tree
        const commentsTree = parseCommentsToTree(parsed.commentsRaw);
        renderCommentTree(commentsTree, document.getElementById("viewer-comments-tree"));
        
    } catch (error) {
        showToast("Error reading file content", "error");
    }
}

// Helper to open results directory on OS explorer
async function openResultsFolder() {
    try {
        const res = await fetch(`${API_BASE}/api/open-folder`, { method: "POST" });
        if (!res.ok) throw new Error();
        showToast("Opening results directory...");
    } catch (e) {
        showToast("Failed to open folder.", "error");
    }
}

// Helper: Copy viewer content for AI summary prompt
function copyViewerContentForAI() {
    if (!currentFileRawContent) return;
    
    navigator.clipboard.writeText(currentFileRawContent)
        .then(() => {
            showToast("Copied full discussion to clipboard!");
        })
        .catch(() => {
            showToast("Failed to copy clipboard.", "error");
        });
}

// --- COMMENTS PARSER ALGORITHMS ---

// Separates metadata headers from comment lines
function parseScrapedFileContent(rawText) {
    const lines = rawText.split('\n');
    let meta = { subreddit: '', title: '', date: '', link: '', commentsRaw: '' };
    let commentsStartIndex = -1;
    
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        if (line.startsWith('SUBREDDIT:')) {
            meta.subreddit = line.replace('SUBREDDIT:', '').trim();
        } else if (line.startsWith('TITLE:')) {
            meta.title = line.replace('TITLE:', '').trim();
        } else if (line.startsWith('DATE:')) {
            meta.date = line.replace('DATE:', '').trim();
        } else if (line.startsWith('LINK:')) {
            meta.link = line.replace('LINK:', '').trim();
        } else if (line.startsWith('COMMENTS:')) {
            commentsStartIndex = i + 1;
            break;
        }
    }
    
    if (commentsStartIndex !== -1) {
        meta.commentsRaw = lines.slice(commentsStartIndex).join('\n');
    }
    
    return meta;
}

// Parses raw string comments with indentation depths into a hierarchical JS Tree structure
function parseCommentsToTree(commentsRaw) {
    const lines = commentsRaw.split('\n');
    let rawCommentsArray = [];
    let currentComment = null;
    
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        
        // 1. Matches Main Comments
        if (line.trim().startsWith('[MAIN COMMENT]:')) {
            if (currentComment) rawCommentsArray.push(currentComment);
            currentComment = {
                type: 'main',
                author: 'Reddit User',
                body: line.replace('[MAIN COMMENT]:', '').trim(),
                depth: 0
            };
        } 
        // 2. Matches Indented Replies
        else if (line.includes('└─ [REPLY]:')) {
            if (currentComment) rawCommentsArray.push(currentComment);
            const prefixIndex = line.indexOf('└─ [REPLY]:');
            const depth = Math.floor(prefixIndex / 2); // 2 spaces per depth increment
            currentComment = {
                type: 'reply',
                author: 'Reddit User',
                body: line.substring(prefixIndex + '└─ [REPLY]:'.length).trim(),
                depth: depth
            };
        } 
        // 3. Matches Deep API fetches
        else if (line.trim().startsWith('[ADDITIONAL COMMENT by')) {
            if (currentComment) rawCommentsArray.push(currentComment);
            const match = line.match(/\[ADDITIONAL COMMENT by ([^\]]+)\]:\s*(.*)/);
            let author = 'Reddit User';
            let body = '';
            if (match) {
                author = match[1];
                body = match[2];
            }
            currentComment = {
                type: 'additional',
                author: author,
                body: body,
                depth: 1 // default nested level for additional listings
            };
        } 
        // 4. Continued comment lines (multiline comment bodies)
        else {
            if (currentComment) {
                currentComment.body += '\n' + line;
            }
        }
    }
    // Push the final comment parsed
    if (currentComment) rawCommentsArray.push(currentComment);
    
    // Convert sequential array with depth ratings into a tree structure
    let treeRoots = [];
    let stack = [];
    
    rawCommentsArray.forEach(c => {
        c.replies = [];
        c.body = c.body.trim();
        
        // Pop comments from the stack until we locate the parent nodes
        while (stack.length > 0 && stack[stack.length - 1].depth >= c.depth) {
            stack.pop();
        }
        
        if (stack.length === 0) {
            c.depth = 0; // top level root
            treeRoots.push(c);
        } else {
            stack[stack.length - 1].replies.push(c);
        }
        stack.push(c);
    });
    
    return treeRoots;
}

// Recursively builds the DOM tree for collapsible hierarchical comments view
function renderCommentTree(commentsList, container) {
    container.innerHTML = "";
    if (commentsList.length === 0) {
        container.innerHTML = `<div class="no-results" style="padding: 40px;">No comments could be processed for this file.</div>`;
        return;
    }
    
    function buildNodeHtml(comment) {
        const node = document.createElement("div");
        node.className = `comment-node ${comment.depth === 0 ? 'main-comment' : 'reply-comment'}`;
        
        // Meta row
        const meta = document.createElement("div");
        meta.className = "comment-meta";
        
        const author = document.createElement("span");
        author.className = "comment-author-badge";
        author.textContent = comment.depth === 0 ? "💬 OP / MAIN THREAD" : `👤 ${comment.author}`;
        
        const tag = document.createElement("span");
        tag.className = "badge";
        tag.style.backgroundColor = comment.depth === 0 ? "var(--primary-light)" : "var(--border-color)";
        tag.style.color = comment.depth === 0 ? "var(--primary)" : "var(--text-muted)";
        tag.textContent = comment.depth === 0 ? "Topic Thread" : `Reply (Lvl ${comment.depth})`;
        
        meta.appendChild(author);
        meta.appendChild(tag);
        
        // Body row
        const body = document.createElement("div");
        body.className = "comment-body";
        body.textContent = comment.body;
        
        node.appendChild(meta);
        node.appendChild(body);
        
        // If replies exist, append nested
        if (comment.replies && comment.replies.length > 0) {
            const repliesDiv = document.createElement("div");
            repliesDiv.className = "replies-container";
            comment.replies.forEach(reply => {
                repliesDiv.appendChild(buildNodeHtml(reply));
            });
            node.appendChild(repliesDiv);
        }
        
        return node;
    }
    
    commentsList.forEach(comment => {
        container.appendChild(buildNodeHtml(comment));
    });
}
