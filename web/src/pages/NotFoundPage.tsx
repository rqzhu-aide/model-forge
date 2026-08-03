import { Link } from "react-router-dom";
import { EmptyState } from "../components/Feedback";

export function NotFoundPage() {
  return (
    <EmptyState title="This research view does not exist" action={<Link to="/" className="button button--primary">Return to projects</Link>}>
      <p>Check the project, phase, or run identifier in the address.</p>
    </EmptyState>
  );
}
