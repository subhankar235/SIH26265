import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { client } from '../../api/client';
import { EmptyState, ErrorState, LoadingState, useToast } from '../../components/common/PageStates';

export default function DiscrepancyBoard() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const query = useQuery({
    queryKey: ['discrepancies'],
    queryFn: () => client.get('/verification/discrepancies').then((response) => response.data),
  });
  const resolve = useMutation({
    mutationFn: (id) => client.post(`/verification/discrepancies/${id}/resolve`, null, {
      params: { remarks: 'Reviewed by officer' },
    }),
    onSuccess: () => {
      toast('Discrepancy marked reviewed.');
      queryClient.invalidateQueries({ queryKey: ['discrepancies'] });
    },
  });

  return (
    <section>
      <h1 className="mb-2 text-3xl font-bold">Discrepancy board</h1>
      <p className="mb-6 text-slate-600">Open OCR and bank mismatches requiring review.</p>
      {query.isLoading ? <LoadingState label="Loading discrepancies" />
        : query.isError ? <ErrorState error={query.error} onRetry={() => query.refetch()} label="Could not load discrepancies" />
          : !query.data?.length ? <EmptyState title="No open discrepancies">Open OCR and bank mismatches will appear here for review.</EmptyState>
            : <div className="space-y-3">{query.data.map((item) => (
              <article key={item.id} className="flex flex-wrap items-center justify-between gap-4 rounded-xl border bg-white p-4">
                <div>
                  <b className="capitalize">{item.field.replaceAll('_', ' ')}</b>
                  <p className="mt-1 text-sm text-slate-600">Declared {item.declared_value} · found {item.extracted_value} · {item.source}</p>
                </div>
                <div className="flex items-center gap-3">
                  <span className="rounded bg-red-50 px-2 py-1 text-xs uppercase text-red-700">{item.severity}</span>
                  <button disabled={resolve.isPending} onClick={() => resolve.mutate(item.id)} className="rounded border px-3 py-1.5 text-sm disabled:opacity-50">Resolve</button>
                </div>
              </article>
            ))}</div>}
      {resolve.isError && <ErrorState error={resolve.error} label="Could not resolve discrepancy" />}
    </section>
  );
}
