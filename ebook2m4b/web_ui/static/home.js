(function () {
  function initSourceModePicker() {
    const sourceModeInputs = document.querySelectorAll("input[name='source_mode']");
    const sourcePanels = document.querySelectorAll("[data-source-panel]");

    if (!sourceModeInputs.length || !sourcePanels.length) {
      return;
    }

    function getSelectedMode() {
      const selected = document.querySelector("input[name='source_mode']:checked");
      return selected ? selected.value : "upload";
    }

    function setPanelActive(panel, active) {
      panel.classList.toggle("active", active);

      const controls = panel.querySelectorAll("input:not([type='radio']), select, textarea");
      controls.forEach((control) => {
        control.disabled = !active;
      });
    }

    function updateSourcePanels() {
      const selectedMode = getSelectedMode();
      sourcePanels.forEach((panel) => {
        const mode = panel.getAttribute("data-source-panel");
        setPanelActive(panel, mode === selectedMode);
      });
    }

    sourceModeInputs.forEach((input) => {
      input.addEventListener("change", updateSourcePanels);
    });

    updateSourcePanels();
  }

  function initSpeakerControls() {
    const engineSelect = document.getElementById("engine-select");
    const speakerSelect = document.getElementById("speaker-select");
    const speakerMeta = document.getElementById("speaker-meta");
    const edgeControls = document.getElementById("edge-controls");
    const edgeLocaleFilter = document.getElementById("edge-locale-filter");

    if (!engineSelect || !speakerSelect || !speakerMeta || !edgeControls || !edgeLocaleFilter) {
      return;
    }

    function renderSpeakerMeta() {
      const selected = speakerSelect.options[speakerSelect.selectedIndex];
      if (!selected) {
        speakerMeta.textContent = "Speaker metadata unavailable.";
        return;
      }

      const language = selected.dataset.language || "Unknown";
      const gender = selected.dataset.gender || "Unknown";
      const quality = selected.dataset.quality || "n/a";
      const training = selected.dataset.training || "n/a";

      speakerMeta.innerHTML =
        "<strong>Speaker profile</strong><br>" +
        `Language: ${language} | Gender: ${gender} | Quality: ${quality} | Training: ${training}`;
    }

    function createSpeakerOption(speaker, preferredSpeakerId) {
      const option = document.createElement("option");
      option.value = speaker.id;
      option.textContent = `${speaker.id} - ${speaker.language} - ${speaker.gender || "Unknown"}${speaker.quality_label ? ` - ${speaker.quality_label}` : ""}`;
      option.dataset.language = speaker.language || "";
      option.dataset.languageCode = speaker.language_code || "";
      option.dataset.gender = speaker.gender || "";
      option.dataset.quality = speaker.quality_label || "";
      option.dataset.training = speaker.training_duration || "";
      if (preferredSpeakerId && speaker.id === preferredSpeakerId) {
        option.selected = true;
      }
      return option;
    }

    function updateEngineControls() {
      const isEdge = engineSelect.value === "edge";
      if (isEdge) {
        edgeControls.removeAttribute("hidden");
      } else {
        edgeControls.setAttribute("hidden", "hidden");
      }
    }

    async function refreshSpeakers() {
      const engineId = engineSelect.value;
      const previousSpeaker = speakerSelect.value;
      const localeFilter = engineId === "edge" ? edgeLocaleFilter.value.trim() : "";
      const query = localeFilter ? `?locale=${encodeURIComponent(localeFilter)}` : "";

      try {
        const response = await fetch(`/api/speakers/${encodeURIComponent(engineId)}${query}`);
        if (!response.ok) {
          throw new Error("Unable to load speakers");
        }
        const payload = await response.json();
        const speakers = payload.speakers || [];

        speakerSelect.innerHTML = "";
        if (!speakers.length) {
          const option = document.createElement("option");
          option.value = "";
          option.textContent = "No speakers available";
          speakerSelect.append(option);
        } else {
          speakers.forEach((speaker, index) => {
            const option = createSpeakerOption(speaker, previousSpeaker);
            if (!previousSpeaker && index === 0) {
              option.selected = true;
            }
            speakerSelect.append(option);
          });
        }
      } catch (_error) {
        speakerMeta.textContent = "Speaker metadata could not be loaded.";
      }

      renderSpeakerMeta();
    }

    engineSelect.addEventListener("change", async function () {
      updateEngineControls();
      await refreshSpeakers();
    });
    edgeLocaleFilter.addEventListener("change", refreshSpeakers);
    speakerSelect.addEventListener("change", renderSpeakerMeta);

    updateEngineControls();
    renderSpeakerMeta();
  }

  initSourceModePicker();
  initSpeakerControls();
})();
