/* ==========================================================================
   EDUPREDICT AI - MAIN CLIENT-SIDE INTERACTIVITY
   ========================================================================== */

document.addEventListener('DOMContentLoaded', () => {
    // 1. Sync Range Sliders with Number Inputs / Displays
    const syncSliders = () => {
        document.querySelectorAll('.input-slider-group').forEach(group => {
            const range = group.querySelector('input[type="range"]');
            const num = group.querySelector('input[type="number"]');
            const display = group.querySelector('.slider-val-box');

            if (range) {
                range.addEventListener('input', (e) => {
                    const val = e.target.value;
                    if (num) num.value = val;
                    if (display) display.textContent = val + (range.dataset.unit || '');
                    triggerLivePrediction();
                });
            }

            if (num) {
                num.addEventListener('input', (e) => {
                    const val = e.target.value;
                    if (range) range.value = val;
                    if (display) display.textContent = val + (range.dataset.unit || '');
                    triggerLivePrediction();
                });
            }
        });
    };

    syncSliders();

    // 2. Interactive Real-Time Prediction API Caller
    const livePredictorContainer = document.querySelector('[data-live-predictor]');
    let debounceTimer;

    function triggerLivePrediction() {
        if (!livePredictorContainer) return;
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            fetchLivePrediction();
        }, 200);
    }

    async function fetchLivePrediction() {
        if (!livePredictorContainer) return;

        const studyHoursInput = document.getElementById('study_hours');
        const attendanceInput = document.getElementById('attendance');
        const prevMarksInput = document.getElementById('previous_marks');
        const assignMarksInput = document.getElementById('assignment_marks');

        if (!studyHoursInput || !attendanceInput || !prevMarksInput || !assignMarksInput) return;

        const payload = {
            study_hours: parseFloat(studyHoursInput.value) || 0,
            attendance: parseFloat(attendanceInput.value) || 0,
            previous_marks: parseFloat(prevMarksInput.value) || 0,
            assignment_marks: parseFloat(assignMarksInput.value) || 0
        };

        try {
            const response = await fetch('/api/predict', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!response.ok) return;
            const data = await response.json();

            // Update UI elements
            const statusBadge = document.getElementById('result-status-badge');
            const statusCard = document.getElementById('result-card');
            const probaFill = document.getElementById('result-proba-fill');
            const probaText = document.getElementById('result-proba-text');
            const adviceText = document.getElementById('result-advice-text');
            const riskText = document.getElementById('result-risk-text');

            if (statusBadge && statusCard) {
                const isPass = data.status === 'Pass';
                statusBadge.textContent = isPass ? '✓ PREDICTED: PASS' : '✗ PREDICTED: FAIL';
                statusBadge.className = `predict-badge-large ${isPass ? 'pass' : 'fail'}`;
                statusCard.className = `predict-result-card ${isPass ? 'pass' : 'fail'}`;
            }

            if (probaFill) {
                probaFill.style.width = `${data.pass_probability}%`;
                probaFill.className = `meter-bar-fill ${data.status === 'Pass' ? 'pass' : 'fail'}`;
            }

            if (probaText) {
                probaText.textContent = `${data.pass_probability}% Pass Probability (${data.confidence}% Confidence)`;
            }

            if (adviceText && data.recommendation) {
                adviceText.textContent = data.recommendation;
            }

            if (riskText && data.risk_level) {
                riskText.textContent = `Risk Assessment: ${data.risk_level}`;
            }

        } catch (err) {
            console.warn('Live prediction fetch error:', err);
        }
    }

    // Quick Scenario presets helper for students and users
    window.setPredictorScenario = (study, attendance, prev, assign) => {
        const studyInput = document.getElementById('study_hours');
        const attendanceInput = document.getElementById('attendance');
        const prevMarksInput = document.getElementById('previous_marks');
        const assignMarksInput = document.getElementById('assignment_marks');

        if (studyInput) { 
            studyInput.value = study; 
            studyInput.dispatchEvent(new Event('input')); 
        }
        if (attendanceInput) { 
            attendanceInput.value = attendance; 
            attendanceInput.dispatchEvent(new Event('input')); 
        }
        if (prevMarksInput) { 
            prevMarksInput.value = prev; 
            prevMarksInput.dispatchEvent(new Event('input')); 
        }
        if (assignMarksInput) { 
            assignMarksInput.value = assign; 
            assignMarksInput.dispatchEvent(new Event('input')); 
        }
        fetchLivePrediction();
    };

    window.triggerManualPrediction = () => {
        fetchLivePrediction();
    };

    // Attach immediate check if predictor is open
    if (livePredictorContainer) {
        fetchLivePrediction();
    }

    // 3. Search and Filter in Student Table
    const searchInput = document.getElementById('studentSearch');
    const filterPills = document.querySelectorAll('.filter-pill');
    const studentRows = document.querySelectorAll('.student-row');

    if (searchInput || filterPills.length > 0) {
        let currentFilter = 'all';

        const applyFilter = () => {
            const query = (searchInput?.value || '').toLowerCase().trim();

            studentRows.forEach(row => {
                const text = row.textContent.toLowerCase();
                const status = row.dataset.status || '';
                const matchesSearch = text.includes(query);
                const matchesFilter = currentFilter === 'all' || status.toLowerCase() === currentFilter.toLowerCase();

                row.style.display = (matchesSearch && matchesFilter) ? '' : 'none';
            });
        };

        if (searchInput) {
            searchInput.addEventListener('input', applyFilter);
        }

        filterPills.forEach(pill => {
            pill.addEventListener('click', (e) => {
                e.preventDefault();
                filterPills.forEach(p => p.classList.remove('active'));
                pill.classList.add('active');
                currentFilter = pill.dataset.filter || 'all';
                applyFilter();
            });
        });
    }

    // 4. Role selector on Signup
    const roleRadios = document.querySelectorAll('input[name="role"]');
    const adminKeyGroup = document.getElementById('admin-code-group');

    if (roleRadios.length > 0 && adminKeyGroup) {
        roleRadios.forEach(radio => {
            radio.addEventListener('change', () => {
                document.querySelectorAll('.role-radio-label').forEach(lbl => lbl.classList.remove('active'));
                radio.closest('.role-radio-label').classList.add('active');

                if (radio.value === 'admin') {
                    adminKeyGroup.style.display = 'block';
                } else {
                    adminKeyGroup.style.display = 'none';
                }
            });
        });
    }

    // 5. Demo Account auto-fillers for Login
    window.fillDemoAccount = (role) => {
        const emailInput = document.getElementById('login-email');
        const passInput = document.getElementById('login-password');

        if (role === 'student') {
            if (emailInput) emailInput.value = 'student@system.com';
            if (passInput) passInput.value = 'student123';
        }
    };
});
