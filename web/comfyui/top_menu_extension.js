import { app } from "../../scripts/app.js";

const CURATOR_PATH = "/curator";
const TOOLTIP = "Open Curator";

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
            icon: "icon-[lucide--images] size-4",
            tooltip: TOOLTIP,
            onClick: openCurator,
        },
    ],
});
