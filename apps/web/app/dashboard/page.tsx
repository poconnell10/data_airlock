import { redirect } from "next/navigation";

/** Legacy path — adjudication queue lives at /adjudication. */
export default function DashboardRedirectPage() {
  redirect("/adjudication");
}
