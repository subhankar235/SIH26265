import { useQuery } from "@tanstack/react-query";
import { client } from "../../api/client";
export default function AuditLogs() {
  const { data = [], isLoading } = useQuery({
    queryKey: ["audit"],
    queryFn: () => client.get("/audit").then((r) => r.data),
  });
  return (
    <section>
      <h1 className="mb-2 text-3xl font-bold">Audit trail</h1>
      <p className="mb-6 text-slate-600">
        Append-only record of state changes.
      </p>
      {isLoading ? (
        <p>Loading…</p>
      ) : (
        <div className="overflow-auto rounded-xl border bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50">
              <tr>
                {["Time", "Actor", "Entity", "Action", "Changes"].map((x) => (
                  <th key={x} className="p-3">
                    {x}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y">
              {data.map((x) => (
                <tr key={x.id}>
                  <td className="whitespace-nowrap p-3">
                    {new Date(x.created_at).toLocaleString()}
                  </td>
                  <td className="p-3">{x.user_id ?? "System"}</td>
                  <td className="p-3">
                    {x.entity} #{x.entity_id}
                  </td>
                  <td className="p-3">{x.action}</td>
                  <td className="max-w-md p-3">
                    <ul className="space-y-1 text-xs">
                      {Object.entries(x.delta_changes || {}).map(([field, change]) => (
                        <li key={field} className="grid grid-cols-[7rem_1fr] gap-2">
                          <span className="font-medium text-slate-600">{field}</span>
                          <span><del className="text-red-700">{String(change?.[0] ?? '—')}</del> <span aria-hidden="true">→</span> <ins className="text-green-800 no-underline">{String(change?.[1] ?? '—')}</ins></span>
                        </li>
                      ))}
                    </ul>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
