import type { ProjectionStamp } from "../api/types";
import { formatDate, shortDigest } from "../utils/format";

export function ProjectionNote({ projection }: { projection: ProjectionStamp }) {
  return (
    <p className="projection-note">
      View revision {projection.view_revision ?? "not recorded"}
      <span aria-hidden="true"> · </span>
      projected {formatDate(projection.projected_at)}
      <span aria-hidden="true"> · </span>
      authority root <code>{shortDigest(projection.authority_event_root_sha256)}</code>
    </p>
  );
}
