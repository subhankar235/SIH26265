import { Stack, useLocalSearchParams } from 'expo-router';
import { Card, Screen, styles, Text } from '../../../components/ui';
import CaseDetailScreen from '../../../screens/CaseDetailScreen';

export default function CaseRoute() {
  const params = useLocalSearchParams();
  const fdrId = Number(params.id);
  if (!Number.isFinite(fdrId) || fdrId <= 0) {
    return <Screen title="Case unavailable">
      <Card><Text style={styles.muted}>This case reference is not valid. Open the case from your portal list instead.</Text></Card>
      <Stack.Screen options={{ title: 'Case file' }}/>
    </Screen>;
  }
  return <CaseDetailScreen fdrId={fdrId}/>;
}
