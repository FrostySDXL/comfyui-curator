import { app } from "../../scripts/app.js";

const CURATOR_PATH = "/curator";
const TOOLTIP = "Open Curator";
const ICON_URL = new URL("./icon.png", import.meta.url).href;
const STYLE_ID = "comfyui-curator-action-bar-style";

if (!document.getElementById(STYLE_ID)) {
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = `
        .curator-header-btn {
            display: inline-block;
            width: 16px;
            height: 16px;
            background: url("${ICON_URL}") center / contain no-repeat;
        }
    `;
    document.head.appendChild(style);
}

function openCurator(event) {
    const url = `${window.location.origin}${CURATOR_PATH}`;
    if (event?.shiftKey) {
        window.open(url, "_blank", "width=1400,height=900,resizable=yes,scrollbars=yes");
        return;
    }
    window.open(url, "_blank");
}

app.registerExtension({
    name: "ComfyUICurator.TopMenu",
    actionBarButtons: [
        {
            icon: "curator-header-btn",
            tooltip: TOOLTIP,
            onClick: openCurator,
        },
    ],
});
